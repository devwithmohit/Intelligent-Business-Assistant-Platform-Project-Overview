import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class EnrichmentError(Exception):
    pass


class EnrichmentService:
    """
    Minimal enrichment service with pluggable providers (Clearbit, Hunter).
    Returns best-effort enrichment dict for a prospect (may be partial).
    """

    def __init__(
        self,
        clearbit_key: Optional[str] = None,
        hunter_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.clearbit_key = clearbit_key
        self.hunter_key = hunter_key
        self._client = httpx.AsyncClient(timeout=timeout)
        self._semaphore = asyncio.Semaphore(8)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        # simple wrapper to centralize error handling
        try:
            resp = await self._client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            logger.debug("Enrichment HTTP error %s %s", url, e)
            raise EnrichmentError(f"provider error: {e}") from e
        except httpx.RequestError as e:
            logger.debug("Enrichment request failed %s %s", url, e)
            raise EnrichmentError(f"request error: {e}") from e

    async def _clearbit_person(self, email: str) -> Optional[Dict[str, Any]]:
        if not self.clearbit_key:
            return None
        url = f"https://person.clearbit.com/v2/people/find?email={httpx.utils.quote(email)}"
        headers = {"Authorization": f"Bearer {self.clearbit_key}"}
        try:
            resp = await self._request("GET", url, headers=headers)
            return resp.json()
        except EnrichmentError:
            return None

    async def _hunter_email_finder(self, email: str, domain: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # Hunter primarily supports domain-based discovery; this is best-effort
        if not self.hunter_key:
            return None
        # If domain provided, use domain+email; else try direct lookup if supported
        params = {"email": email, "api_key": self.hunter_key}
        if domain:
            params["domain"] = domain
        url = "https://api.hunter.io/v2/email-finder"
        try:
            resp = await self._request("GET", url, params=params)
            data = resp.json()
            return data.get("data") or data
        except EnrichmentError:
            return None

    async def enrich_prospect(self, prospect: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich a single prospect dict. Prospect may include keys: email, domain, name.
        Returns a dict with enrichment fields merged (may be empty if no providers configured).
        """
        if not isinstance(prospect, dict):
            raise TypeError("prospect must be a dict")

        email = prospect.get("email")
        domain = prospect.get("company_domain") or prospect.get("domain") or None
        out: Dict[str, Any] = {}

        # If no providers configured, return original prospect unmodified
        if not (self.clearbit_key or self.hunter_key):
            logger.debug("No enrichment providers configured; returning prospect unchanged")
            return {**prospect, **out}

        # Acquire semaphore to limit concurrent provider calls
        async with self._semaphore:
            # Try Clearbit first (usually richer person/company data)
            if email and self.clearbit_key:
                try:
                    cb = await self._clearbit_person(email=email)
                    if cb:
                        # map common fields
                        out.setdefault("name", cb.get("name", {}).get("fullName") or cb.get("name"))
                        out.setdefault("email", email)
                        out.setdefault("title", cb.get("employment", {}).get("title") or cb.get("title"))
                        out.setdefault("company", cb.get("employment", {}).get("name") or (cb.get("company") or {}).get("name"))
                        out.setdefault("linkedin", cb.get("linkedin") or cb.get("linkedin_url") or cb.get("site"))
                        out["raw_clearbit"] = cb
                except Exception:
                    logger.debug("Clearbit enrichment failed for %s", email, exc_info=True)

            # Next try Hunter (email discovery / verification)
            if email and self.hunter_key and not out.get("email_verified"):
                try:
                    hn = await self._hunter_email_finder(email=email, domain=domain)
                    if hn:
                        # hunter returns 'result' or 'score' and other fields depending on endpoint
                        out.setdefault("email", hn.get("email") or out.get("email") or email)
                        if "status" in hn:
                            out.setdefault("email_verified", hn.get("status") == "valid")
                        out.setdefault("company", out.get("company") or hn.get("company", {}).get("name") if isinstance(hn.get("company"), dict) else out.get("company"))
                        out["raw_hunter"] = hn
                except Exception:
                    logger.debug("Hunter enrichment failed for %s", email, exc_info=True)

            # If we still lack company info and domain provided, set it
            if domain and not out.get("company"):
                out.setdefault("company", domain)

        # Merge original prospect data (original keys should not be overwritten if enrichment exists)
        merged = {**prospect, **{k: v for k, v in out.items() if v is not None}}
        return merged

    async def enrich_batch(self, prospects: List[Dict[str, Any]], concurrency: int = 8) -> List[Dict[str, Any]]:
        """
        Enrich a batch of prospects concurrently (bounded by concurrency).
        """
        sem = asyncio.Semaphore(concurrency)
        results: List[Dict[str, Any]] = []

        async def _work(p: Dict[str, Any]):
            async with sem:
                try:
                    return await self.enrich_prospect(p)
                except Exception:
                    logger.exception("enrich_prospect failed for %s", p)
                    return p

        tasks = [asyncio.create_task(_work(p)) for p in prospects]
        for t in asyncio.as_completed(tasks):
            res = await t
            results.append(res)
        return results

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


# Module-level default service
_default_service: Optional[EnrichmentService] = None


def _get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        from ..core import config as core_config  # type: ignore
        return getattr(core_config.settings, name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


def _ensure_service() -> EnrichmentService:
    global _default_service
    if _default_service is None:
        cb = _get_setting("ENRICHMENT_CLEARBIT_KEY") or _get_setting("CLEARBIT_KEY")
        hunter = _get_setting("ENRICHMENT_HUNTER_KEY") or _get_setting("HUNTER_KEY")
        _default_service = EnrichmentService(clearbit_key=cb, hunter_key=hunter)
    return _default_service


# Convenience wrappers
async def enrich_prospect(prospect: Dict[str, Any]) -> Dict[str, Any]:
    svc = _ensure_service()
    return await svc.enrich_prospect(prospect)


async def enrich_batch(prospects: List[Dict[str, Any]], concurrency: int = 8) -> List[Dict[str, Any]]:
    svc = _ensure_service()
    return await svc.enrich_batch(prospects, concurrency=concurrency)
