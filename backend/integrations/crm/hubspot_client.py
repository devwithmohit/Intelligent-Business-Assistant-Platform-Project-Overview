import asyncio
import logging
from typing import Any, Dict, List, Optional

try:
    from hubspot import HubSpot  # type: ignore
    from hubspot.crm.contacts import SimplePublicObjectInput  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    HubSpot = None  # type: ignore
    SimplePublicObjectInput = None  # type: ignore

logger = logging.getLogger(__name__)


class HubspotClientError(Exception):
    pass


class HubspotClient:
    """
    Async-friendly thin wrapper around HubSpot official client.
    Supports connecting with api_key or OAuth access token (via developer-provided credentials).
    All blocking calls are executed in a threadpool to avoid blocking the event loop.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self.timeout = timeout
        self._client = None

    async def connect(self) -> None:
        if HubSpot is None:
            raise HubspotClientError("hubspot-api-client library not installed")

        if self._client:
            return

        loop = asyncio.get_running_loop()

        def _build():
            try:
                if self.access_token:
                    return HubSpot(access_token=self.access_token)
                if self.api_key:
                    return HubSpot(api_key=self.api_key)
                raise HubspotClientError("no credentials provided for HubSpot client")
            except Exception:
                logger.exception("Failed to initialize HubSpot client")
                raise

        try:
            self._client = await loop.run_in_executor(None, _build)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def _ensure(self) -> None:
        if not self._client:
            await self.connect()

    async def get_contact(
        self, contact_id: str, properties: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _get():
            try:
                props = properties or []
                resp = self._client.crm.contacts.basic_api.get_by_id(
                    contact_id, properties=props
                )
                return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)
            except Exception as exc:
                logger.exception("Failed to get contact %s", contact_id)
                raise

        try:
            return await loop.run_in_executor(None, _get)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def create_contact(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _create():
            try:
                if SimplePublicObjectInput is not None:
                    body = SimplePublicObjectInput(properties=properties)
                    resp = self._client.crm.contacts.basic_api.create(
                        simple_public_object_input=body
                    )
                else:
                    resp = self._client.crm.contacts.basic_api.create(
                        body=properties
                    )  # fallback shape
                return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)
            except Exception as exc:
                logger.exception("Failed to create contact")
                raise

        try:
            return await loop.run_in_executor(None, _create)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def update_contact(
        self, contact_id: str, properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _update():
            try:
                body = {"properties": properties}
                resp = self._client.crm.contacts.basic_api.update(
                    contact_id, simple_public_object_input=body
                )
                return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)
            except Exception as exc:
                logger.exception("Failed to update contact %s", contact_id)
                raise

        try:
            return await loop.run_in_executor(None, _update)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def search_contacts(
        self,
        query: str,
        properties: Optional[List[str]] = None,
        limit: int = 25,
        after: Optional[int] = None,
    ) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _search():
            try:
                req = {
                    "filterGroups": [
                        {
                            "filters": [
                                {
                                    "value": query,
                                    "propertyName": "email",
                                    "operator": "EQ",
                                }
                            ]
                        }
                    ],
                    "properties": properties or [],
                    "limit": limit,
                }
                # HubSpot client provides search_api; using generic post for compatibility
                resp = self._client.crm.contacts.search_api.do_search(body=req)
                return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)
            except Exception as exc:
                logger.exception("Contact search failed for query=%s", query)
                raise

        try:
            return await loop.run_in_executor(None, _search)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def create_deal(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _create_deal():
            try:
                body = {"properties": properties}
                resp = self._client.crm.deals.basic_api.create(
                    simple_public_object_input=body
                )
                return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)
            except Exception as exc:
                logger.exception("Failed to create deal")
                raise

        try:
            return await loop.run_in_executor(None, _create_deal)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def get_company(
        self, company_id: str, properties: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _get_comp():
            try:
                resp = self._client.crm.companies.basic_api.get_by_id(
                    company_id, properties=properties or []
                )
                return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)
            except Exception as exc:
                logger.exception("Failed to get company %s", company_id)
                raise

        try:
            return await loop.run_in_executor(None, _get_comp)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc

    async def associate_contact_company(
        self,
        contact_id: str,
        company_id: str,
        association_type: str = "company_to_contact",
    ) -> bool:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _assoc():
            try:
                # association types vary; use associations API
                self._client.crm.contacts.associations_api.create(
                    contact_id, "company", company_id, association_type
                )
                return True
            except Exception as exc:
                logger.exception(
                    "Failed to associate contact %s with company %s",
                    contact_id,
                    company_id,
                )
                raise

        try:
            return await loop.run_in_executor(None, _assoc)
        except Exception as exc:
            raise HubspotClientError(str(exc)) from exc
