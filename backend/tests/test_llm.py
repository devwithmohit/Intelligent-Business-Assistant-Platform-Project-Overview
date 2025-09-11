import asyncio
import pytest

from backend.schemas.lm_schemas import LLMRequest, ChatMessage
from backend.services import model_router, llm_service


def test_router_selects_known_task():
    route = model_router.select_model("content")
    assert isinstance(route, dict)
    assert "provider" in route and "model" in route


@pytest.mark.asyncio
async def test_generate_primary_success(monkeypatch):
    req = LLMRequest(task="chat", messages=[ChatMessage(role="user", content="Hello")])

    async def fake_call_provider(provider, model, req_arg):
        # simulate typical provider response shape
        return {"choices": [{"message": {"content": "Hi there!"}}]}

    monkeypatch.setattr(llm_service, "_call_provider", fake_call_provider)

    resp = await llm_service.generate(req)
    assert resp.text is not None
    assert "Hi there" in resp.text
    # provider should be whatever select_model chose (we didn't override it)
    assert resp.provider is not None


@pytest.mark.asyncio
async def test_generate_primary_failure_then_fallback(monkeypatch):
    # force selection to a known primary provider to control behavior
    monkeypatch.setattr(model_router, "select_model", lambda task, constraints=None: {"provider": "openrouter", "model": "m1", "reason": "test"})
    # ensure fallback_for uses defaults (deepseek)
    # simulate primary failure and fallback success
    async def fake_call_provider(provider, model, req_arg):
        if provider == "openrouter":
            raise RuntimeError("primary failed")
        if provider == "deepseek":
            return {"output": "fallback response"}
        raise RuntimeError("unexpected provider")

    monkeypatch.setattr(llm_service, "_call_provider", fake_call_provider)

    req = LLMRequest(task="chat", prompt="Hello")
    resp = await llm_service.generate(req)
    # fallback path sets provider field to "fallback:<provider>"
    assert resp.provider and ("fallback" in resp.provider or resp.provider.startswith("fallback:"))
    assert "fallback response" in resp.text


@pytest.mark.asyncio
async def test_embed_prefers_deepseek_and_returns_embeddings(monkeypatch):
    # stub deepseek client with an embed method
    async def fake_embed(model, inputs, **kw):
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    class StubDeepSeek:
        async def embed(self, model, inputs, **kw):
            return await fake_embed(model, inputs, **kw)

    # inject stub client
    monkeypatch.setattr(llm_service, "_deepseek", StubDeepSeek())
    # ensure openrouter stub not used
    monkeypatch.setattr(llm_service, "_openrouter", None)

    res = await llm_service.embed(["hello world"], model_hint=None, model="deeps-embed-1")
    assert hasattr(res, "embeddings")
    assert isinstance(res.embeddings, list)
    assert len(res.embeddings) == 1
    assert isinstance(res.embeddings[0], list)
