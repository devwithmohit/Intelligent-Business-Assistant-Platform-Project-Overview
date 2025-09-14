import asyncio
import logging
from typing import Any, Dict, Optional, List, Union

from .email_interface import create_email_client, send as email_send, EmailClientInterface, EmailIntegrationError

logger = logging.getLogger(__name__)


class EmailServiceError(Exception):
    pass


class EmailService:
    """
    High-level async email orchestration service.
    - Manages named email integration configurations and client instances.
    - Provides async helpers: authorize, send_email, list_messages, get_message.
    """

    def __init__(self, integrations_cfg: Optional[Dict[str, Dict[str, Any]]] = None):
        # mapping name -> config dict (as provided in integrations_config)
        self._cfg: Dict[str, Dict[str, Any]] = integrations_cfg or {}
        # cache of created client instances: name -> EmailClientInterface
        self._clients: Dict[str, EmailClientInterface] = {}
        self._lock = asyncio.Lock()

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        """Register or update a named integration config (does not eagerly create client)."""
        async with self._lock:
            self._cfg[name] = cfg
            # drop cached client so new config takes effect next time
            if name in self._clients:
                try:
                    del self._clients[name]
                except Exception:
                    logger.debug("Failed to drop cached client %s", name)

    async def _create_client(self, name: str) -> EmailClientInterface:
        cfg = self._cfg.get(name)
        if not cfg:
            raise EmailServiceError(f"integration not found: {name}")
        try:
            client = create_email_client(cfg)
            return client
        except EmailIntegrationError as e:
            raise EmailServiceError(str(e)) from e

    async def get_client(self, name: str) -> EmailClientInterface:
        """Return or create a cached EmailClientInterface for the named integration."""
        async with self._lock:
            client = self._clients.get(name)
            if client:
                return client
            client = await self._create_client(name)
            self._clients[name] = client
            return client

    async def authorize(self, name: str, **kwargs) -> Any:
        """Run provider-specific authorization flow (e.g. OAuth local server) if supported."""
        client = await self.get_client(name)
        try:
            return await client.authorize(**kwargs)
        except Exception as e:
            logger.exception("Authorization failed for email integration %s", name)
            raise EmailServiceError(str(e)) from e

    async def send_email(
        self,
        integration_name: str,
        to: Union[str, List[str]],
        subject: str,
        body_text: str,
        html: Optional[str] = None,
        thread_id: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send email via named integration. Uses adapter send() to normalize provider differences."""
        client = await self.get_client(integration_name)
        try:
            return await email_send(client, to=to, subject=subject, body_text=body_text, html=html, thread_id=thread_id, cc=cc, bcc=bcc)
        except EmailIntegrationError as e:
            raise EmailServiceError(str(e)) from e
        except Exception as e:
            logger.exception("Failed to send email via %s", integration_name)
            raise EmailServiceError(str(e)) from e

    async def list_messages(self, integration_name: str, query: Optional[str] = None, max_results: int = 50) -> List[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            return await client.list_messages(query=query, max_results=max_results)
        except Exception as e:
            logger.exception("Failed to list messages for %s", integration_name)
            raise EmailServiceError(str(e)) from e

    async def get_message(self, integration_name: str, message_id: str, format: str = "full") -> Optional[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            return await client.get_message(message_id=message_id, format=format)
        except Exception as e:
            logger.exception("Failed to fetch message %s for %s", message_id, integration_name)
            raise EmailServiceError(str(e)) from e


# module-level singleton
_default_email_service: Optional[EmailService] = None


def get_email_service(cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> EmailService:
    global _default_email_service
    if _default_email_service is None:
        _default_email_service = EmailService(integrations_cfg=cfg)
    return _default_email_service
