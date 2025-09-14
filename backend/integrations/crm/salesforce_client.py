import asyncio
import logging
from typing import Any, Dict, List, Optional

try:
    from simple_salesforce import Salesforce  # type: ignore
except Exception:  # pragma: no cover - import may not be available in test env
    Salesforce = None  # type: ignore

logger = logging.getLogger(__name__)


class SalesforceClientError(Exception):
    pass


class SalesforceClient:
    """
    Minimal async-friendly wrapper around simple_salesforce.Salesforce.
    Supports connecting with (username, password, security_token) or with (session_id, instance_url).
    All blocking calls are executed in a threadpool via asyncio.get_running_loop().run_in_executor.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        security_token: Optional[str] = None,
        domain: str = "login",
        session_id: Optional[str] = None,
        instance_url: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> None:
        self.username = username
        self.password = password
        self.security_token = security_token
        self.domain = domain
        self.session_id = session_id
        self.instance_url = instance_url
        self.client_id = client_id
        self._sf = None

    async def connect(self) -> None:
        if Salesforce is None:
            raise SalesforceClientError("simple-salesforce library not installed")

        if self._sf:
            return

        loop = asyncio.get_running_loop()

        def _connect():
            try:
                if self.session_id and self.instance_url:
                    return Salesforce(session_id=self.session_id, instance_url=self.instance_url)
                if self.username and self.password:
                    return Salesforce(
                        username=self.username,
                        password=self.password,
                        security_token=self.security_token,
                        domain=self.domain,
                        client_id=self.client_id,
                    )
                raise SalesforceClientError("insufficient credentials to connect to Salesforce")
            except Exception as exc:
                logger.exception("Salesforce connect failed")
                raise

        try:
            self._sf = await loop.run_in_executor(None, _connect)
        except Exception as exc:
            raise SalesforceClientError(str(exc)) from exc

    async def _ensure(self) -> None:
        if not self._sf:
            await self.connect()

    async def query(self, soql: str) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _q():
            return self._sf.query(soql)

        try:
            return await loop.run_in_executor(None, _q)
        except Exception as exc:
            logger.exception("Salesforce SOQL query failed")
            raise SalesforceClientError(str(exc)) from exc

    async def get_sobject(self, object_name: str, record_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _get():
            return getattr(self._sf, object_name).get(record_id)

        try:
            return await loop.run_in_executor(None, _get)
        except Exception as exc:
            logger.exception("Failed to fetch %s id=%s", object_name, record_id)
            raise SalesforceClientError(str(exc)) from exc

    async def create_sobject(self, object_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _create():
            return getattr(self._sf, object_name).create(data)

        try:
            return await loop.run_in_executor(None, _create)
        except Exception as exc:
            logger.exception("Failed to create %s", object_name)
            raise SalesforceClientError(str(exc)) from exc

    async def update_sobject(self, object_name: str, record_id: str, updates: Dict[str, Any]) -> None:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _update():
            getattr(self._sf, object_name).update(record_id, updates)
            return None

        try:
            return await loop.run_in_executor(None, _update)
        except Exception as exc:
            logger.exception("Failed to update %s id=%s", object_name, record_id)
            raise SalesforceClientError(str(exc)) from exc

    async def upsert_sobject(self, object_name: str, external_id_field: str, external_id_value: str, data: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _upsert():
            return getattr(self._sf, object_name).upsert(f"{external_id_field}/{external_id_value}", data)

        try:
            return await loop.run_in_executor(None, _upsert)
        except Exception as exc:
            logger.exception("Failed to upsert %s on %s=%s", object_name, external_id_field, external_id_value)
            raise SalesforceClientError(str(exc)) from exc

    async def delete_sobject(self, object_name: str, record_id: str) -> bool:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _del():
            return getattr(self._sf, object_name).delete(record_id)

        try:
            resp = await loop.run_in_executor(None, _del)
            # simple-salesforce returns dict with 'id' on success; treat truthy as success
            return bool(resp)
        except Exception as exc:
            logger.exception("Failed to delete %s id=%s", object_name, record_id)
            raise SalesforceClientError(str(exc)) from exc

    async def search(self, sosl: str) -> Dict[str, Any]:
        await self._ensure()
        loop = asyncio.get_running_loop()

        def _search():
            return self._sf.search(sosl)

        try:
            return await loop.run_in_executor(None, _search)
        except Exception as exc:
            logger.exception("Salesforce SOSL search failed")
            raise SalesforceClientError(str(exc)) from exc


# convenience factory --------------------------------------------------------
_default_salesforce_client: Optional[SalesforceClient] = None


def get_salesforce_client(cfg: Optional[Dict[str, Any]] = None) -> SalesforceClient:
    """
    Return a configured SalesforceClient singleton. cfg may contain keys:
      username, password, security_token, domain, session_id, instance_url, client_id
    """
    global _default_salesforce_client
    if _default_salesforce_client is None:
        cfg = cfg or {}
        _default_salesforce_client = SalesforceClient(
            username=cfg.get("username"),
            password=cfg.get("password"),
            security_token=cfg.get("security_token"),
            domain=cfg.get("domain", "login"),
            session_id=cfg.get("session_id"),
            instance_url=cfg.get("instance_url"),
            client_id=cfg.get("client_id"),
        )
    return _default_salesforce_client
