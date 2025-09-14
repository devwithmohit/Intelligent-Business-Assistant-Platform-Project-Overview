import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from exchangelib import Account, Credentials, Configuration, DELEGATE, CalendarItem  # type: ignore

logger = logging.getLogger(__name__)


class OutlookCalendarClient:
    """
    Async-friendly wrapper around exchangelib.Account calendar operations.
    Uses run_in_executor to avoid blocking the event loop.

    Basic usage:
      client = OutlookCalendarClient(email="me@example.com", username="DOMAIN\\user", password="secret")
      await client.list_events(...)
      await client.create_event({...})
    """

    def __init__(
        self,
        email: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        credentials: Optional[Credentials] = None,
        autodiscover: bool = True,
    ) -> None:
        self.email = email
        self._credentials = credentials or (Credentials(username, password) if username and password else None)
        self._server = server
        self._autodiscover = autodiscover
        self._account: Optional[Account] = None

    async def _get_account(self) -> Account:
        if self._account:
            return self._account

        loop = asyncio.get_running_loop()

        def _build():
            cfg = None
            if self._server:
                cfg = Configuration(server=self._server, credentials=self._credentials) if self._credentials else None
            return Account(primary_smtp_address=self.email, credentials=self._credentials, autodiscover=self._autodiscover, config=cfg, access_type=DELEGATE)

        try:
            self._account = await loop.run_in_executor(None, _build)
            return self._account
        except Exception as exc:
            logger.exception("Failed to initialize Outlook account for %s: %s", self.email, exc)
            raise

    async def list_events(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List calendar events within an optional window. If no window provided returns recent events.
        Returns a list of lightweight dicts.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _list():
            try:
                if start and end:
                    items = acct.calendar.view(start=start, end=end)
                else:
                    # fallback: recent events ordered by start
                    items = acct.calendar.all().order_by("start")[:max_results]
                out = []
                for it in items[:max_results]:
                    out.append(
                        {
                            "id": str(getattr(it, "item_id", getattr(it, "id", ""))),
                            "subject": getattr(it, "subject", ""),
                            "start": getattr(it, "start", None),
                            "end": getattr(it, "end", None),
                            "location": getattr(it, "location", None),
                            "organizer": getattr(it, "organizer", None).__dict__ if getattr(it, "organizer", None) else None,
                            "attendees": [getattr(a, "email", None) for a in getattr(it, "required_attendees", [])] or [],
                        }
                    )
                return out
            except Exception:
                logger.exception("Failed to list calendar events for %s", self.email)
                return []

        return await loop.run_in_executor(None, _list)

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single calendar event by id (best-effort). Returns parsed dict or None.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _get():
            try:
                # exchangelib supports get by id via .get(id=...)
                item = acct.calendar.get(id=event_id)
                return {
                    "id": str(getattr(item, "item_id", getattr(item, "id", ""))),
                    "subject": getattr(item, "subject", ""),
                    "start": getattr(item, "start", None),
                    "end": getattr(item, "end", None),
                    "location": getattr(item, "location", None),
                    "body": getattr(item, "body", None).body if getattr(item, "body", None) else None,
                    "attendees": [getattr(a, "email", None) for a in getattr(item, "required_attendees", [])] or [],
                }
            except Exception:
                logger.exception("Failed to fetch calendar event id=%s for %s", event_id, self.email)
                return None

        return await loop.run_in_executor(None, _get)

    async def create_event(self, event_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a calendar event.
        event_body expected keys: subject, start (datetime), end (datetime), location (opt), body (opt), attendees (list of emails)
        Returns a dict with created event metadata.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _create():
            try:
                kwargs = {}
                if "subject" in event_body:
                    kwargs["subject"] = event_body["subject"]
                if "start" in event_body:
                    kwargs["start"] = event_body["start"]
                if "end" in event_body:
                    kwargs["end"] = event_body["end"]
                if "location" in event_body:
                    kwargs["location"] = event_body["location"]
                if "body" in event_body:
                    kwargs["body"] = event_body["body"]
                if "attendees" in event_body:
                    # exchangelib expects attendee objects; simple use of email strings via required_attendees may work
                    kwargs["required_attendees"] = event_body["attendees"]

                item = CalendarItem(account=acct, folder=acct.calendar, **kwargs)
                item.save()
                return {"id": str(getattr(item, "item_id", getattr(item, "id", ""))), "subject": item.subject}
            except Exception:
                logger.exception("Failed to create calendar event for %s", self.email)
                raise

        return await loop.run_in_executor(None, _create)

    async def update_event(self, event_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update a calendar event by id. Returns updated event metadata or None on failure.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _patch():
            try:
                item = acct.calendar.get(id=event_id)
                if not item:
                    return None
                # apply simple updates
                if "subject" in updates:
                    item.subject = updates["subject"]
                if "start" in updates:
                    item.start = updates["start"]
                if "end" in updates:
                    item.end = updates["end"]
                if "location" in updates:
                    item.location = updates["location"]
                if "body" in updates:
                    item.body = updates["body"]
                item.save()
                return {"id": str(getattr(item, "item_id", getattr(item, "id", ""))), "subject": item.subject}
            except Exception:
                logger.exception("Failed to update calendar event id=%s for %s", event_id, self.email)
                return None

        return await loop.run_in_executor(None, _patch)

    async def delete_event(self, event_id: str) -> bool:
        """
        Delete an event by id. Returns True on success, False otherwise.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _del():
            try:
                item = acct.calendar.get(id=event_id)
                if not item:
                    return False
                item.delete()
                return True
            except Exception:
                logger.exception("Failed to delete calendar event id=%s for %s", event_id, self.email)
                return False

        return await loop.run_in_executor(None, _del)
