import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CRMIntegrationError(Exception):
    pass


class CRMClientInterface(ABC):
    """Abstract async CRM client interface used by higher-level services."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish client session / validate credentials."""
        raise NotImplementedError

    @abstractmethod
    async def get_contact(
        self, contact_id: str, properties: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def search_contacts(
        self, query: str, properties: Optional[List[str]] = None, limit: int = 25
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def create_contact(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def update_contact(
        self, contact_id: str, properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def create_deal(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_company(
        self, company_id: str, properties: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


def create_crm_client(cfg: Dict[str, Any]) -> CRMClientInterface:
    """
    Factory to create provider-backed CRM client.
    cfg example:
      { "type": "salesforce", ... }
      { "type": "hubspot", ... }
    """
    provider = (cfg or {}).get("type", "").lower()
    if provider in ("salesforce", "sf"):
        try:
            from .salesforce_client import SalesforceClient  # local import
        except Exception as e:
            logger.exception("Failed to import SalesforceClient")
            raise CRMIntegrationError("salesforce client not available") from e
        return SalesforceClient(
            username=cfg.get("username"),
            password=cfg.get("password"),
            security_token=cfg.get("security_token"),
            domain=cfg.get("domain", "login"),
            session_id=cfg.get("session_id"),
            instance_url=cfg.get("instance_url"),
            client_id=cfg.get("client_id"),
        )

    if provider in ("hubspot", "hs"):
        try:
            from .hubspot_client import HubspotClient  # local import
        except Exception as e:
            logger.exception("Failed to import HubspotClient")
            raise CRMIntegrationError("hubspot client not available") from e
        return HubspotClient(
            api_key=cfg.get("api_key"), access_token=cfg.get("access_token")
        )

    raise CRMIntegrationError(f"unsupported crm provider type: {provider}")


# small adapter helpers -----------------------------------------------------
async def find_contact_by_email(
    client: CRMClientInterface, email: str, properties: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Try to locate a contact by email. Uses provider search capabilities.
    Returns first matching contact dict or None.
    """
    try:
        resp = await client.search_contacts(
            query=email, properties=properties or [], limit=1
        )
        # provider search shapes differ; try common keys
        hits = None
        if isinstance(resp, dict):
            hits = (
                resp.get("results")
                or resp.get("records")
                or resp.get("items")
                or resp.get("contacts")
            )
        if not hits:
            return None
        first = hits[0]
        return first if isinstance(first, dict) else dict(first)
    except Exception as exc:
        logger.exception("find_contact_by_email failed for %s", email)
        raise CRMIntegrationError(str(exc)) from exc


async def upsert_contact_normalized(
    client: CRMClientInterface,
    external_id_field: str,
    external_id_value: str,
    properties: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Best-effort upsert helper. Providers may implement upsert; otherwise attempt get/create/update.
    Returns created/updated object.
    """
    try:
        # try to use provider-specific upsert if available
        if hasattr(client, "upsert_sobject"):
            # salesforce-style upsert
            upsert = getattr(client, "upsert_sobject")
            return await upsert(
                "Contact", external_id_field, external_id_value, properties
            )
        # hubspot: try to search then create/update
        # attempt to find by external id
        found = await find_contact_by_email(client, external_id_value)
        if found:
            cid = found.get("id") or found.get("vid") or found.get("contactId")
            if cid:
                return await client.update_contact(cid, properties)
        return await client.create_contact(properties)
    except Exception as exc:
        logger.exception("upsert_contact_normalized failed")
        raise CRMIntegrationError(str(exc)) from exc
