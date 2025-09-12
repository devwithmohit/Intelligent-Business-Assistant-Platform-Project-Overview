import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class CRMError(Exception):
    pass


class CRMClient:
    """
    Minimal async CRM client wrapper.
    Provides: get_contact, get_contact_by_email, create_ticket, update_lead.
    """

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str = "https://api.example-crm.com",
        timeout: float = 15.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
    ) -> None:
        if not api_key:
            raise CRMError("CRM API key is required")
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
                # don't retry on most 4xx except 429
                if status_code and 400 <= status_code < 500 and status_code != 429:
                    logger.debug("CRM request failed (non-retriable): %s %s", status_code, exc)
                    raise CRMError(f"CRM error: {status_code} - {exc}") from exc
                sleep = self.backoff_factor * (2 ** attempt)
                logger.warning("CRM request failed, retrying in %.2fs (attempt %d): %s", sleep, attempt + 1, exc)
                await asyncio.sleep(sleep)
        raise CRMError("CRM request failed") from last_exc

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/v1/contacts/{contact_id}")

    async def get_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        resp = await self._request("GET", "/v1/contacts", params={"email": email})
        # assume list results
        if isinstance(resp, dict):
            items = resp.get("data") or resp.get("results") or resp.get("contacts") or []
        else:
            items = []
        return items[0] if items else None

    async def create_ticket(self, customer_id: Optional[str], subject: str, description: str, priority: str = "normal") -> Dict[str, Any]:
        payload = {"subject": subject, "description": description, "priority": priority}
        if customer_id:
            payload["customer_id"] = customer_id
        return await self._request("POST", "/v1/tickets", json=payload)

    async def update_lead(self, lead_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("PATCH", f"/v1/leads/{lead_id}", json=data)

    async def close(self) -> None:
        if not self._closed:
            await self._client.aclose()
            self._closed = True


# module-level lazy client using settings/env
_client: Optional[CRMClient] = None


def _get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        from ..core import config as core_config  # type: ignore
        return getattr(core_config.settings, name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


def _ensure_client() -> Optional[CRMClient]:
    global _client
    if _client is None:
        key = _get_setting("CRM_API_KEY") or _get_setting("DEMO_CRM_KEY")
        base = _get_setting("CRM_URL") or "https://api.example-crm.com"
        if key:
            try:
                _client = CRMClient(api_key=key, base_url=base)
            except Exception as e:
                logger.warning("Failed to init CRM client: %s", e)
                _client = None
    return _client


# convenience async wrappers used by agents/services
async def get_contact(contact_id: str) -> Dict[str, Any]:
    client = _ensure_client()
    if not client:
        raise CRMError("CRM client not configured")
    return await client.get_contact(contact_id)


async def get_contact_by_email(email: str) -> Optional[Dict[str, Any]]:
    client = _ensure_client()
    if not client:
        raise CRMError("CRM client not configured")
    return await client.get_contact_by_email(email)


async def create_ticket(customer_id: Optional[str], subject: str, description: str, priority: str = "normal") -> Dict[str, Any]:
    client = _ensure_client()
    if not client:
        raise CRMError("CRM client not configured")
    return await client.create_ticket(customer_id=customer_id, subject=subject, description=description, priority=priority)


async def update_lead(lead_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    client = _ensure_client()
    if not client:
        raise CRMError("CRM client not configured")