import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    pass


class OpenRouterClient:
    """
    Minimal async client for OpenRouter (Gemini via OpenRouter API).
    Usage:
      client = OpenRouterClient(api_key="...", base_url="https://api.openrouter.ai")
      await client.generate_chat(model="gemini-1.5", messages=[{"role":"user","content":"hi"}])
    """

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str = "https://api.openrouter.ai",
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
    ) -> None:
        if not api_key:
            raise OpenRouterError("OpenRouter API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._closed = False

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"Bearer {self.api_key}")
        headers.setdefault("Content-Type", "application/json")

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.request(method, url, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                # don't retry on 4xx except 429
                status = getattr(exc, "response", None)
                status_code = status.status_code if status is not None else None
                if status_code and 400 <= status_code < 500 and status_code != 429:
                    logger.debug("OpenRouter request failed (non-retriable): %s %s", status_code, exc)
                    raise OpenRouterError(f"OpenRouter error: {status_code} - {exc}") from exc
                sleep = self.backoff_factor * (2 ** attempt)
                logger.warning("OpenRouter request failed, retrying in %.2fs (attempt %d): %s", sleep, attempt + 1, exc)
                await asyncio.sleep(sleep)
        raise OpenRouterError("OpenRouter request failed") from last_exc

    async def generate_chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **extra,
    ) -> Dict[str, Any]:
        """
        Send chat-style request. `messages` should be list of {"role": "user|assistant|system", "content": "..."}.
        Returns the parsed JSON response.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)
        return await self._request("POST", "/v1/chat/completions", json=payload)

    async def generate_completion(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **extra,
    ) -> Dict[str, Any]:
        """
        Send completion-style request (non-chat) if needed.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "input": prompt,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)
        # Some OpenRouter endpoints use /v1/completions or /v1/chat/completions; try chat endpoint as default.
        return await self._request("POST", "/v1/completions", json=payload)

    async def close(self) -> None:
        if not self._closed:
            await self._client.aclose()
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
