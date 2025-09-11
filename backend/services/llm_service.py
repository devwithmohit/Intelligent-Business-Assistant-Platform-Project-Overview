import asyncio
import logging
import os
from typing import Any, Dict, Optional

from .models.openrouter_client import OpenRouterClient, OpenRouterError
from .models.deepseek_client import DeepSeekClient, DeepSeekError
from .model_router import select_model, fallback_for
from ..schemas.lm_schemas import LLMRequest, LLMResponse, GenerationChoice, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)

# lazy singletons for provider clients
_openrouter: Optional[OpenRouterClient] = None
_deepseek: Optional[DeepSeekClient] = None


def _get_settings_value(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        from ..core import config as core_config  # type: ignore
        return getattr(core_config.settings, name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


def _ensure_clients():
    global _openrouter, _deepseek
    if _openrouter is None:
        key = _get_settings_value("OPENROUTER_KEY")
        if key:
            try:
                _openrouter = OpenRouterClient(api_key=key, base_url=_get_settings_value("OPENROUTER_URL", "https://api.openrouter.ai"))
            except Exception as e:
                logger.warning("OpenRouter client init failed: %s", e)
                _openrouter = None
    if _deepseek is None:
        key = _get_settings_value("DEEPSEEK_API_KEY")
        if key:
            try:
                _deepseek = DeepSeekClient(api_key=key, base_url=_get_settings_value("DEEPSEEK_URL", "https://api.deepseek.ai"))
            except Exception as e:
                logger.warning("DeepSeek client init failed: %s", e)
                _deepseek = None


def _extract_text_from_response(resp: Any) -> str:
    """
    Best-effort normalizer for provider responses.
    """
    if resp is None:
        return ""
    try:
        # OpenRouter/Chat-like: choices -> [ { message: { content: "..." } } ]
        choices = resp.get("choices") if isinstance(resp, dict) else None
        if choices and isinstance(choices, list) and len(choices) > 0:
            first = choices[0]
            # message.content
            if isinstance(first, dict):
                msg = first.get("message") or first.get("delta")
                if isinstance(msg, dict):
                    content = msg.get("content") or msg.get("content_text") or msg.get("text")
                    if content:
                        return content
                # fallback to text field
                if first.get("text"):
                    return first.get("text")
            # if choices items are strings
            if isinstance(first, str):
                return first

        # DeepSeek-like: maybe resp['output'] or resp['data'] or resp['text']
        if isinstance(resp, dict):
            for k in ("output", "text", "data", "result"):
                v = resp.get(k)
                if isinstance(v, str):
                    return v
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    # try first element text
                    txt = v[0].get("text") or v[0].get("content")
                    if txt:
                        return txt
        # fallback to JSON stringification
        return str(resp)
    except Exception:
        return str(resp)


async def _call_provider(provider: str, model: str, req: LLMRequest) -> Dict[str, Any]:
    _ensure_clients()
    logger.debug("llm_service: calling provider=%s model=%s task=%s", provider, model, req.task)
    # Chat-style if messages provided
    if provider == "openrouter" and _openrouter:
        if req.messages:
            messages = [m.dict() for m in req.messages]
            return await _openrouter.generate_chat(model=model, messages=messages, **(req.params or {}))
        # non-chat completion
        if req.prompt:
            return await _openrouter.generate_completion(model=model, prompt=req.prompt, **(req.params or {}))
        raise OpenRouterError("No input provided for generation")
    elif provider == "deepseek" and _deepseek:
        # prefer embed endpoint for embeddings
        if req.task == "embeddings" and req.prompt:
            # if prompt is a single string, send as single-item list
            inputs = [req.prompt]
            return await _deepseek.embed(model=model, inputs=inputs, **(req.params or {}))
        if req.messages:
            # convert messages to a single prompt for DeepSeek if needed
            prompt = "\n".join(f"{m.role}: {m.content}" for m in req.messages)
            return await _deepseek.generate_text(model=model, prompt=prompt, **(req.params or {}))
        if req.prompt:
            return await _deepseek.generate_text(model=model, prompt=req.prompt, **(req.params or {}))
        raise DeepSeekError("No input provided for generation")
    else:
        raise RuntimeError(f"Provider client not configured: {provider}")


async def generate(req: LLMRequest) -> LLMResponse:
    """
    High-level generation entrypoint.
    Attempts primary provider chosen by model_router and falls back to alternate provider on failure.
    Returns normalized LLMResponse.
    """
    constraints = {"model_hint": req.model_hint} if req.model_hint else {}
    selection = select_model(req.task or "chat", constraints=constraints)
    provider = selection.get("provider")
    model = req.model_hint or selection.get("model")
    reason = selection.get("reason")
    logger.info("llm_service.generate selected provider=%s model=%s reason=%s", provider, model, reason)

    last_exc: Optional[Exception] = None

    # Try primary provider
    try:
        resp = await _call_provider(provider, model, req)
        text = _extract_text_from_response(resp)
        choices = []
        # try to populate choices list if present
        try:
            raw_choices = resp.get("choices") if isinstance(resp, dict) else None
            if raw_choices and isinstance(raw_choices, list):
                for idx, c in enumerate(raw_choices):
                    if isinstance(c, dict):
                        txt = None
                        if c.get("message"):
                            txt = c.get("message", {}).get("content")
                        txt = txt or c.get("text") or c.get("content") or _extract_text_from_response(c)
                        choices.append(GenerationChoice(text=txt, index=idx))
        except Exception:
            choices = []
        return LLMResponse(text=text or "", choices=choices or None, provider=provider, raw=resp, meta={"model": model, "reason": reason})
    except Exception as exc:
        logger.exception("llm_service: primary provider %s failed: %s", provider, exc)
        last_exc = exc

    # Try fallback provider
    fb = fallback_for(provider) or ("deepseek" if provider != "deepseek" else "openrouter")
    logger.info("llm_service: trying fallback provider=%s", fb)
    try:
        resp = await _call_provider(fb, model, req)
        text = _extract_text_from_response(resp)
        return LLMResponse(text=text or "", provider=f"fallback:{fb}", raw=resp, meta={"model": model, "fallback_from": provider})
    except Exception as exc2:
        logger.exception("llm_service: fallback provider %s failed: %s", fb, exc2)
        # raise last exception or combined
        raise RuntimeError(f"LLM generation failed: primary error={last_exc}, fallback error={exc2}") from exc2


async def embed(inputs: list[str], model_hint: Optional[str] = None, model: Optional[str] = None) -> EmbeddingResponse:
    """
    Request embeddings for a list of strings. Prefers DeepSeek, falls back to OpenRouter.
    """
    _ensure_clients()
    chosen = model_hint or model or "deeps-embed-1"
    # prefer deepseek
    try:
        if _deepseek:
            resp = await _deepseek.embed(model=chosen, inputs=inputs)
            # normalize embeddings
            embeddings = []
            if isinstance(resp, dict):
                data = resp.get("data") or resp.get("embeddings") or resp.get("embedding")
                # try common shapes
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    for item in data:
                        emb = item.get("embedding") or item.get("vector") or item.get("embeddings")
                        if isinstance(emb, list):
                            embeddings.append(emb)
                elif isinstance(data, list) and isinstance(data[0], list):
                    embeddings = data
            return EmbeddingResponse(embeddings=embeddings, model=chosen, raw=resp)
    except Exception as e:
        logger.warning("embed via deepseek failed: %s", e)

    # fallback to openrouter if available
    try:
        if _openrouter:
            # OpenRouter embedding endpoints may vary; try /v1/embeddings via client if provided
            resp = await _openrouter._request("POST", "/v1/embeddings", json={"model": chosen, "input": inputs})
            embeddings = resp.get("data") or resp.get("embeddings") or []
            return EmbeddingResponse(embeddings=embeddings, model=chosen, raw=resp)
    except Exception as e:
        logger.warning("embed via openrouter failed: %s", e)

    raise RuntimeError("Embeddings generation failed for all providers")
