import asyncio
import logging
from typing import Any, Dict, List, Optional

from .crm_interface import (
    create_crm_client,
    find_contact_by_email,
    upsert_contact_normalized,
    CRMIntegrationError,
    CRMClientInterface,
)

logger = logging.getLogger(__name__)


class CRMSyncError(Exception):
    pass


class CRMSyncService:
    """
    High-level CRM sync & mapping service.

    - Manage named CRM integration configs and client instances.
    - Provide helpers to sync contacts/deals between integrations with simple field mapping.
    - Uses adapter helpers in crm_interface for provider differences.
    """

    def __init__(self, integrations_cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._cfg: Dict[str, Dict[str, Any]] = integrations_cfg or {}
        self._clients: Dict[str, CRMClientInterface] = {}
        self._lock = asyncio.Lock()

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        async with self._lock:
            self._cfg[name] = cfg
            if name in self._clients:
                try:
                    del self._clients[name]
                except Exception:
                    logger.debug("Failed to drop cached CRM client %s", name)

    async def _create_client(self, name: str) -> CRMClientInterface:
        cfg = self._cfg.get(name)
        if not cfg:
            raise CRMSyncError(f"integration not found: {name}")
        try:
            return create_crm_client(cfg)
        except CRMIntegrationError as e:
            raise CRMSyncError(str(e)) from e

    async def get_client(self, name: str) -> CRMClientInterface:
        async with self._lock:
            client = self._clients.get(name)
            if client:
                return client
            client = await self._create_client(name)
            self._clients[name] = client
            return client

    # --- mapping helpers ---
    @staticmethod
    def _map_fields(src: Dict[str, Any], mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Map source dict keys to destination keys using mapping { src_key: dst_key }.
        If mapping is None, return src as-is (shallow copy).
        """
        if not mapping:
            return dict(src)
        out: Dict[str, Any] = {}
        for sk, sv in src.items():
            dk = mapping.get(sk, sk)
            out[dk] = sv
        return out

    @staticmethod
    def _normalize_contact_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Best-effort normalization of varying contact shapes into a flat properties dict.
        """
        props: Dict[str, Any] = {}
        # common shapes: {"properties": {...}}, or top-level keys
        if "properties" in raw and isinstance(raw["properties"], dict):
            props.update(raw["properties"])
        else:
            # flatten nested 'properties' like HubSpot responses or pass-through keys
            for k, v in raw.items():
                if k in ("id", "vid", "contactId"):
                    continue
                if isinstance(v, dict) and "value" in v:
                    props[k] = v.get("value")
                else:
                    props[k] = v
        return props

    # --- sync operations ---
    async def sync_contacts(
        self,
        src_integration: str,
        dst_integration: str,
        field_mapping: Optional[Dict[str, str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List recent contacts from src and upsert into dst using optional field_mapping.
        Returns summary { 'copied': n, 'skipped': n, 'errors': [...] }.
        """
        out = {"copied": 0, "skipped": 0, "errors": []}
        try:
            src = await self.get_client(src_integration)
            dst = await self.get_client(dst_integration)
            # attempt to list contacts - clients may expose different methods; try common ones
            items = []
            if hasattr(src, "list_contacts"):
                items = await src.list_contacts(limit=limit)  # type: ignore
            elif hasattr(src, "search_contacts"):
                # fallback: search for all recent contacts by empty query / special provider behavior
                try:
                    resp = await src.search_contacts(query="", limit=limit)  # type: ignore
                    # try to extract records/results
                    if isinstance(resp, dict):
                        items = resp.get("results") or resp.get("records") or resp.get("contacts") or []
                    else:
                        items = list(resp)
                except Exception:
                    items = []
            else:
                # provider may not support listing; bail
                raise CRMSyncError(f"source integration {src_integration} does not support contact listing")

            for it in items[:limit]:
                try:
                    raw = it if isinstance(it, dict) else dict(it)
                    props = self._normalize_contact_payload(raw)
                    mapped = self._map_fields(props, field_mapping)
                    # choose an external id field to upsert by - default to email if available
                    email = mapped.get("email") or mapped.get("email_address") or mapped.get("work_email")
                    if email:
                        # upsert by email via helper
                        await upsert_contact_normalized(dst, external_id_field="email", external_id_value=email, properties=mapped)
                        out["copied"] += 1
                    else:
                        # no reliable external id - attempt create
                        await dst.create_contact(mapped)  # type: ignore
                        out["copied"] += 1
                except Exception as e:
                    logger.exception("Failed to sync contact %s", it.get("id") if isinstance(it, dict) else None)
                    out["errors"].append({"id": it.get("id") if isinstance(it, dict) else None, "error": str(e)})
            return out
        except Exception as e:
            logger.exception("sync_contacts failed from %s to %s", src_integration, dst_integration)
            raise CRMSyncError(str(e)) from e

    async def sync_contact_by_email(
        self,
        src_integration: str,
        dst_integration: str,
        email: str,
        field_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch a single contact by email from src and upsert into dst.
        """
        try:
            src = await self.get_client(src_integration)
            dst = await self.get_client(dst_integration)
            found = await find_contact_by_email(src, email)  # type: ignore
            if not found:
                raise CRMSyncError(f"contact not found in {src_integration} for {email}")
            props = self._normalize_contact_payload(found)
            mapped = self._map_fields(props, field_mapping)
            res = await upsert_contact_normalized(dst, external_id_field="email", external_id_value=email, properties=mapped)
            return {"result": res}
        except Exception as e:
            logger.exception("sync_contact_by_email failed for %s -> %s email=%s", src_integration, dst_integration, email)
            raise CRMSyncError(str(e)) from e

    async def sync_deals(
        self,
        src_integration: str,
        dst_integration: str,
        field_mapping: Optional[Dict[str, str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Copy deals/opportunities from src to dst with optional field mapping.
        Note: provider shapes differ; this is a best-effort implementation.
        """
        out = {"copied": 0, "errors": []}
        try:
            src = await self.get_client(src_integration)
            dst = await self.get_client(dst_integration)
            items = []
            if hasattr(src, "list_deals"):
                items = await src.list_deals(limit=limit)  # type: ignore
            elif hasattr(src, "query"):
                # SOQL / generic query fallback may be provided by Salesforce wrapper
                try:
                    qresp = await src.query("SELECT Id, Name, Amount, CloseDate FROM Opportunity LIMIT %d" % limit)  # type: ignore
                    items = qresp.get("records", []) if isinstance(qresp, dict) else []
                except Exception:
                    items = []
            else:
                raise CRMSyncError(f"source integration {src_integration} does not support deal listing")

            for it in items[:limit]:
                try:
                    raw = it if isinstance(it, dict) else dict(it)
                    props = self._normalize_contact_payload(raw)
                    mapped = self._map_fields(props, field_mapping)
                    # attempt to create deal on dst
                    if hasattr(dst, "create_deal"):
                        await dst.create_deal(mapped)  # type: ignore
                        out["copied"] += 1
                    else:
                        out["errors"].append({"id": raw.get("id"), "error": "destination does not support create_deal"})
                except Exception as e:
                    logger.exception("Failed to sync deal %s", it.get("id") if isinstance(it, dict) else None)
                    out["errors"].append({"id": it.get("id") if isinstance(it, dict) else None, "error": str(e)})
            return out
        except Exception as e:
            logger.exception("sync_deals failed from %s to %s", src_integration, dst_integration)
            raise CRMSyncError(str(e)) from e


# module-level singleton
_default_crm_sync_service: Optional[CRMSyncService] = None


def get_crm_sync_service(cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> CRMSyncService:
    global _default_crm_sync_service
    if _default_crm_sync_service is None:
        _default_crm_sync_service = CRMSyncService(integrations_cfg=cfg)
    return _default_crm_sync_service
