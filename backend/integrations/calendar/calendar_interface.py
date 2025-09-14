import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CalendarIntegrationError(Exception):
    pass


class CalendarClientInterface(ABC):
    """Abstract async calendar client interface used by higher-level services."""

    @abstractmethod
    async def authorize(self, **kwargs) -> Any:
        """Perform any interactive/async authorization (OAuth flows)."""
        raise NotImplementedError

    @abstractmethod
    async def list_events(
        self,
        start: Optional[Any] = None,
        end: Optional[Any] = None,
        max_results: int = 50,
        q: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List events within an optional window."""
        raise NotImplementedError

    @abstractmethod
    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a single event by id."""
        raise NotImplementedError

    @abstractmethod
    async def create_event(self, event_body: Dict[str, Any]) -> Dict[str, Any]:
        """Create an event given an event resource dict."""
        raise NotImplementedError

    @abstractmethod
    async def update_event(self, event_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update an existing event."""
        raise NotImplementedError

    @abstractmethod
    async def delete_event(self, event_id: str) -> bool:
        """Delete an event by id."""
        raise NotImplementedError


def create_calendar_client(cfg: Dict[str, Any]) -> CalendarClientInterface:
    """
    Factory to create a provider-backed calendar client.
    cfg examples:
      { "type": "google", "client_secrets_path": "...", "token_path": "..." }
      { "type": "outlook", "email": "me@example.com", "username": "...", "password": "..." }
    """
    provider = (cfg or {}).get("type", "").lower()
    if provider == "google":
        try:
            from .google_calendar_client import GoogleCalendarClient  # local import to avoid heavy deps
        except Exception as e:
            logger.exception("Failed to import GoogleCalendarClient")
            raise CalendarIntegrationError("google calendar client not available") from e
        return GoogleCalendarClient(
            client_secrets_path=cfg.get("client_secrets_path"),
            token_path=cfg.get("token_path"),
            scopes=cfg.get("scopes"),
            credentials=cfg.get("credentials"),
            calendar_id=cfg.get("calendar_id", "primary"),
        )

    if provider in ("outlook", "exchange", "ews"):
        try:
            from .outlook_calendar_client import OutlookCalendarClient
        except Exception as e:
            logger.exception("Failed to import OutlookCalendarClient")
            raise CalendarIntegrationError("outlook calendar client not available") from e
        return OutlookCalendarClient(
            email=cfg.get("email"),
            username=cfg.get("username"),
            password=cfg.get("password"),
            server=cfg.get("server"),
            credentials=cfg.get("credentials"),
            autodiscover=cfg.get("autodiscover", True),
        )

    raise CalendarIntegrationError(f"unsupported calendar provider type: {provider}")


# small adapter helpers -----------------------------------------------------
async def create_event_normalized(client: CalendarClientInterface, subject: str, start: Any, end: Any, attendees: Optional[List[str]] = None, location: Optional[str] = None, body: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience wrapper to build a minimal event resource and call client.create_event.
    Keeps callers provider-agnostic.
    """
    event = {
        "summary": subject,
        "subject": subject,  # some providers expect 'subject'
        "start": {"dateTime": start.isoformat()} if hasattr(start, "isoformat") else {"dateTime": str(start)},
        "end": {"dateTime": end.isoformat()} if hasattr(end, "isoformat") else {"dateTime": str(end)},
    }
    if attendees:
        # google expects list of {"email":...}, outlook wrapper accepts list of emails
        event["attendees"] = [{"email": a} for a in attendees]
        event["attendees_emails"] = attendees
    if location:
        event["location"] = location
    if body:
        event["body"] = body
    try:
        return await client.create_event(event)
    except Exception as exc:
        logger.exception("create_event_normalized failed")
        raise CalendarIntegrationError(str(exc)) from exc
