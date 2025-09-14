import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from .messaging_interface import (
    create_messaging_client,
    broadcast as messaging_broadcast,
    notify_user as messaging_notify_user,
    MessagingIntegrationError,
)
from ..email.email_service import get_email_service, EmailServiceError

logger = logging.getLogger(__name__)


class NotificationServiceError(Exception):
    pass


class NotificationService:
    """
    Multi-channel notification orchestration.

    - Register integrations by name (delegates email registrations to EmailService).
    - Send via messaging integrations (Slack/Teams) or email integrations.
    - Provide broadcast and user-notify helpers with best-effort fallbacks.
    """

    def __init__(self, integrations_cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        # name -> cfg
        self._cfg: Dict[str, Dict[str, Any]] = integrations_cfg or {}
        # cached messaging clients: name -> client instance
        self._clients: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        # reuse email service singleton
        self._email_service = get_email_service()

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        """
        Register or update a named integration.
        cfg should include "type" key ('slack'|'teams'|'email' etc).
        """
        async with self._lock:
            self._cfg[name] = cfg
            # drop cached client if present
            if name in self._clients:
                try:
                    del self._clients[name]
                except Exception:
                    logger.debug("Failed to drop cached client %s", name)
        # if this is an email integration, register with EmailService as well
        if (cfg or {}).get("type", "").lower() == "email":
            try:
                await self._email_service.register_integration(name, cfg)
            except Exception:
                logger.debug("Failed to register email integration %s with EmailService", name)

    async def _get_messaging_client(self, name: str):
        async with self._lock:
            client = self._clients.get(name)
            if client:
                return client
            cfg = self._cfg.get(name)
            if not cfg:
                raise NotificationServiceError(f"messaging integration not found: {name}")
            try:
                client = create_messaging_client(cfg)
                self._clients[name] = client
                return client
            except MessagingIntegrationError as exc:
                raise NotificationServiceError(str(exc)) from exc

    async def send_via_messaging(
        self,
        integration_name: str,
        channel: Optional[str],
        text: str,
        subject: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send to a channel or user via a messaging integration.
        If user_id is provided, attempts direct message first (with fallback).
        Returns provider result or raises NotificationServiceError.
        """
        try:
            client = await self._get_messaging_client(integration_name)
            if user_id:
                return await messaging_notify_user(client, user_id=user_id, text=text, subject=subject)
            return await client.send_message(channel=channel, text=text, subject=subject)
        except Exception as exc:
            logger.exception("Messaging send failed for integration=%s channel=%s", integration_name, channel)
            raise NotificationServiceError(str(exc)) from exc

    async def broadcast(
        self, integration_name: str, channels: List[str], text: str, subject: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Broadcast the same message to multiple channels (best-effort)."""
        try:
            client = await self._get_messaging_client(integration_name)
            return await messaging_broadcast(client, channels=channels, text=text, subject=subject)
        except Exception as exc:
            logger.exception("Broadcast failed for integration=%s", integration_name)
            raise NotificationServiceError(str(exc)) from exc

    async def send_via_email(
        self,
        integration_name: str,
        to: Union[str, List[str]],
        subject: str,
        body_text: str,
        html: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email via a registered email integration."""
        try:
            return await self._email_service.send_email(integration_name, to=to, subject=subject, body_text=body_text, html=html)
        except EmailServiceError as exc:
            logger.exception("Email send failed for integration=%s", integration_name)
            raise NotificationServiceError(str(exc)) from exc

    async def notify(
        self,
        *,
        integration_name: Optional[str] = None,
        channels: Optional[List[str]] = None,
        text: str,
        subject: Optional[str] = None,
        user_id: Optional[str] = None,
        email_to: Optional[Union[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """
        High-level notify helper:
         - If integration_name references an email integration and email_to provided -> send email.
         - If integration_name is messaging -> send to channels or user_id.
         - If channels provided without integration_name, will attempt to use all matching messaging integrations.
         Returns a summary dict with results and errors.
        """
        out = {"results": [], "errors": []}

        # If explicit email target
        if integration_name and (self._cfg.get(integration_name, {}).get("type", "").lower() == "email" or email_to):
            try:
                to_target = email_to or channels or []
                res = await self.send_via_email(integration_name or list(self._cfg.keys())[0], to=to_target, subject=subject or "", body_text=text)
                out["results"].append({"channel": "email", "result": res})
            except Exception as exc:
                out["errors"].append({"channel": "email", "error": str(exc)})
            return out

        # Messaging path
        # If explicit integration_name, use it
        if integration_name:
            try:
                if channels:
                    res = await self.broadcast(integration_name, channels=channels, text=text, subject=subject)
                    out["results"].append({"integration": integration_name, "result": res})
                else:
                    res = await self.send_via_messaging(integration_name, channel=None, text=text, subject=subject, user_id=user_id)
                    out["results"].append({"integration": integration_name, "result": res})
            except Exception as exc:
                out["errors"].append({"integration": integration_name, "error": str(exc)})
            return out

        # No integration specified: attempt to send via all messaging integrations registered
        async with self._lock:
            messaging_names = [n for n, c in self._cfg.items() if c.get("type", "").lower() in ("slack", "teams", "msteams")]
        if not messaging_names:
            raise NotificationServiceError("no messaging integrations registered")

        for name in messaging_names:
            try:
                if channels:
                    res = await self.broadcast(name, channels=channels, text=text, subject=subject)
                else:
                    res = await self.send_via_messaging(name, channel=None, text=text, subject=subject, user_id=user_id)
                out["results"].append({"integration": name, "result": res})
            except Exception as exc:
                out["errors"].append({"integration": name, "error": str(exc)})
        return out


# module-level singleton
_default_notification_service: Optional[NotificationService] = None


def get_notification_service(cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> NotificationService:
    global _default_notification_service
    if _default_notification_service is None:
        _default_notification_service = NotificationService(integrations_cfg=cfg)
    return _default_notification_service
