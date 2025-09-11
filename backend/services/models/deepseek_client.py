import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    """
    Minimal async client for DeepSeek API.
    Usage:
      client = DeepSeekClient(api_key="...", base_url="https://api.deepseek.ai")
      await client.generate_text(model="deeps-1", prompt="Write a short summary")
      await client.embed(texts=["hello", "world"])
    """

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str = "https://api.deepseek.ai",
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
    ) -> None:
        if not api_key:
            raise DeepSeekError("DeepSeek API key is required")
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
                status = getattr(exc, "response", None)
                status_code = status.status_code if status is not None else None
                # Do not retry on client errors except 429
                if status_code and 400 <= status_code < 500 and status_code != 429:
                    logger.debug("DeepSeek request failed (non-retriable): %s %s", status_code, exc)
                    raise DeepSeekError(f"DeepSeek error: {status_code} - {exc}") from exc
                sleep = self.backoff_factor * (2 ** attempt)
                logger.warning("DeepSeek request failed, retrying in %.2fs (attempt %d): %s", sleep, attempt + 1, exc)
                await asyncio.sleep(sleep)
        raise DeepSeekError("DeepSeek request failed") from last_exc

    async def generate_text(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **extra,
    ) -> Dict[str, Any]:
        """
        Generate text/completion from DeepSeek.
        Payload keys may vary depending on DeepSeek API; this uses a common shape.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        # common DeepSeek endpoint for generation; adjust if your provider differs
        return await self._request("POST", "/v1/generate", json=payload)

    async def embed(self, model: str, inputs: List[str], **extra) -> Dict[str, Any]:
        """
        Request embeddings for a list of input texts.
        Returns provider response (expected to include embeddings field).
        """
        payload = {"model": model, "inputs": inputs}
        if extra:
            payload.update(extra)
        return await self._request("POST", "/v1/embeddings", json=payload)

    async def close(self) -> None:
        if not self._closed:
            await self._client.aclose()
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
