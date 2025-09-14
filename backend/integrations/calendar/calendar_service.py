import asyncio
import logging
from typing import Any, Dict, List, Optional

from .calendar_interface import (
    create_calendar_client,
    create_event_normalized,
    CalendarClientInterface,
    CalendarIntegrationError,
)

logger = logging.getLogger(__name__)


class CalendarServiceError(Exception):
    pass


class CalendarService:
    """
    High-level calendar orchestration service.
    - Manage named calendar integration configs and client instances.
    - Provide common operations (authorize, list/get/create/update/delete, schedule).
    """

    def __init__(self, integrations_cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._cfg: Dict[str, Dict[str, Any]] = integrations_cfg or {}
        self._clients: Dict[str, CalendarClientInterface] = {}
        self._lock = asyncio.Lock()

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        """Register or update a named calendar integration config."""
        async with self._lock:
            self._cfg[name] = cfg
            if name in self._clients:
                try:
                    del self._clients[name]
                except Exception:
                    logger.debug("Failed to drop cached calendar client %s", name)

    async def _create_client(self, name: str) -> CalendarClientInterface:
        cfg = self._cfg.get(name)
        if not cfg:
            raise CalendarServiceError(f"integration not found: {name}")
        try:
            return create_calendar_client(cfg)
        except CalendarIntegrationError as e:
            raise CalendarServiceError(str(e)) from e

    async def get_client(self, name: str) -> CalendarClientInterface:
        """Return or create a cached CalendarClientInterface for the named integration."""
        async with self._lock:
            client = self._clients.get(name)
            if client:
                return client
            client = await self._create_client(name)
            self._clients[name] = client
            return client

    async def authorize(self, name: str, **kwargs) -> Any:
        """Run provider-specific authorization (e.g. OAuth) for a named integration."""
        client = await self.get_client(name)
        try:
            return await client.authorize(**kwargs)
        except Exception as e:
            logger.exception("Calendar authorization failed for %s", name)
            raise CalendarServiceError(str(e)) from e

    async def list_events(self, integration_name: str, start: Optional[Any] = None, end: Optional[Any] = None, max_results: int = 50, q: Optional[str] = None) -> List[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            return await client.list_events(start=start, end=end, max_results=max_results, q=q)
        except Exception as e:
            logger.exception("Failed to list events for %s", integration_name)
            raise CalendarServiceError(str(e)) from e

    async def get_event(self, integration_name: str, event_id: str) -> Optional[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            return await client.get_event(event_id=event_id)
        except Exception as e:
            logger.exception("Failed to fetch event %s for %s", event_id, integration_name)
            raise CalendarServiceError(str(e)) from e

    async def create_event(self, integration_name: str, event_body: Dict[str, Any]) -> Dict[str, Any]:
        client = await self.get_client(integration_name)
        try:
            return await client.create_event(event_body)
        except Exception as e:
            logger.exception("Failed to create event via %s", integration_name)
            raise CalendarServiceError(str(e)) from e

    async def update_event(self, integration_name: str, event_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            return await client.update_event(event_id, updates)
        except Exception as e:
            logger.exception("Failed to update event %s for %s", event_id, integration_name)
            raise CalendarServiceError(str(e)) from e

    async def delete_event(self, integration_name: str, event_id: str) -> bool:
        client = await self.get_client(integration_name)
        try:
            return await client.delete_event(event_id)
        except Exception as e:
            logger.exception("Failed to delete event %s for %s", event_id, integration_name)
            raise CalendarServiceError(str(e)) from e

    async def schedule_event(
        self,
        integration_name: str,
        subject: str,
        start: Any,
        end: Any,
        attendees: Optional[List[str]] = None,
        location: Optional[str] = None,
        body: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience wrapper that builds a normalized event resource and creates it via the named integration.
        Uses create_event_normalized helper to adapt provider shapes.
        """
        client = await self.get_client(integration_name)
        try:
            return await create_event_normalized(client, subject=subject, start=start, end=end, attendees=attendees, location=location, body=body)
        except Exception as e:
            logger.exception("Failed to schedule event via %s", integration_name)
            raise CalendarServiceError(str(e)) from e

    async def sync_between(self, src_integration: str, dst_integration: str, query: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Simple best-effort sync: lists recent events from src and attempts to create them in dst.
        Returns summary dict: { 'copied': n, 'errors': [...] }
        (Idempotency / dedupe is left to caller / future enhancement.)
        """
        out = {"copied": 0, "errors": []}
        try:
            src_client = await self.get_client(src_integration)
            dst_client = await self.get_client(dst_integration)
            items = await src_client.list_events(q=query, max_results=limit)
            for it in items:
                try:
                    # attempt to map minimal fields into normalized create
                    subject = it.get("summary") or it.get("subject") or "Event"
                    start = it.get("start") or it.get("start_time") or it.get("startDateTime")
                    end = it.get("end") or it.get("end_time") or it.get("endDateTime")
                    attendees = None
                    # normalize possible attendee shapes
                    if it.get("attendees"):
                        attendees = [a.get("email") if isinstance(a, dict) else a for a in it.get("attendees")]
                    await create_event_normalized(dst_client, subject=subject, start=start, end=end, attendees=attendees, location=it.get("location"), body=it.get("body") or it.get("description"))
                    out["copied"] += 1
                except Exception as e:
                    logger.exception("Failed to copy event %s", it.get("id"))
                    out["errors"].append({"id": it.get("id"), "error": str(e)})
            return out
        except Exception as e:
            logger.exception("Calendar sync failed from %s to %s", src_integration, dst_integration)
            raise CalendarServiceError(str(e)) from e


# module-level singleton
_default_calendar_service: Optional[CalendarService] = None


def get_calendar_service(cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> CalendarService:
    global _default_calendar_service
    if _default_calendar_service is None:
        _default_calendar_service = CalendarService(integrations_cfg=cfg)
    return _default_calendar_service
