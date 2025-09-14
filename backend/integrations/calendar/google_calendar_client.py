import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from googleapiclient.discovery import build  # type: ignore

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarClient:
    """
    Minimal Google Calendar client wrapper with async-friendly methods.
    - authorize_via_local_server: run OAuth local server flow (threaded)
    - load_credentials_from_token: load/refresh saved token
    - list_events: list upcoming events
    - get_event / create_event / update_event / delete_event
    All blocking google-api calls are executed in a threadpool via run_in_executor.
    """

    def __init__(
        self,
        client_secrets_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        credentials: Optional[Credentials] = None,
        calendar_id: str = "primary",
    ) -> None:
        self.client_secrets_path = client_secrets_path
        self.token_path = token_path
        self.scopes = scopes or CALENDAR_SCOPES
        self._creds = credentials
        self._service = None
        self.calendar_id = calendar_id

    async def authorize_via_local_server(self, host: str = "localhost", port: int = 0, open_browser: bool = True) -> Credentials:
        if not self.client_secrets_path:
            raise ValueError("client_secrets_path required for OAuth authorization")

        loop = asyncio.get_running_loop()

        def _flow():
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_path, scopes=self.scopes)
            creds = flow.run_local_server(host=host, port=port, open_browser=open_browser)
            if self.token_path:
                try:
                    p = self.token_path
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write(creds.to_json())
                except Exception:
                    logger.debug("Failed to save calendar token to %s", self.token_path, exc_info=True)
            return creds

        creds = await loop.run_in_executor(None, _flow)
        self._creds = creds
        self._service = None
        return creds

    async def load_credentials_from_token(self) -> Optional[Credentials]:
        if not self.token_path:
            return None
        loop = asyncio.get_running_loop()

        def _load():
            try:
                p = self.token_path
                with open(p, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                creds = Credentials.from_authorized_user_info(data, scopes=self.scopes)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                return creds
            except Exception:
                logger.debug("Failed to load/refresh calendar credentials from %s", self.token_path, exc_info=True)
                return None

        creds = await loop.run_in_executor(None, _load)
        if creds:
            self._creds = creds
        return creds

    async def _get_service(self):
        if self._service:
            return self._service
        if not self._creds:
            await self.load_credentials_from_token()
        if not self._creds:
            raise RuntimeError("No credentials available; call authorize_via_local_server or provide credentials/token")

        loop = asyncio.get_running_loop()

        def _build():
            return build("calendar", "v3", credentials=self._creds)

        self._service = await loop.run_in_executor(None, _build)
        return self._service

    async def list_events(self, time_min: Optional[datetime] = None, time_max: Optional[datetime] = None, max_results: int = 50, q: Optional[str] = None) -> List[Dict[str, Any]]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _list():
            tm_min = time_min.isoformat() if time_min else datetime.now(timezone.utc).isoformat()
            req = service.events().list(calendarId=self.calendar_id, timeMin=tm_min, timeMax=time_max.isoformat() if time_max else None, maxResults=max_results, singleEvents=True, orderBy="startTime", q=q)
            resp = req.execute()
            return resp.get("items", [])

        try:
            items = await loop.run_in_executor(None, _list)
            return items
        except Exception:
            logger.exception("Failed to list calendar events")
            return []

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _get():
            return service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()

        try:
            return await loop.run_in_executor(None, _get)
        except Exception:
            logger.exception("Failed to fetch calendar event id=%s", event_id)
            return None

    async def create_event(self, event_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        event_body should follow Google Calendar event resource shape.
        Example minimal:
          {
            "summary": "Meeting",
            "start": {"dateTime": "2025-09-14T15:00:00Z"},
            "end": {"dateTime": "2025-09-14T16:00:00Z"},
            "attendees": [{"email": "user@example.com"}]
          }
        """
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _create():
            return service.events().insert(calendarId=self.calendar_id, body=event_body).execute()

        try:
            return await loop.run_in_executor(None, _create)
        except Exception:
            logger.exception("Failed to create calendar event")
            raise

    async def update_event(self, event_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _patch():
            return service.events().patch(calendarId=self.calendar_id, eventId=event_id, body=updates).execute()

        try:
            return await loop.run_in_executor(None, _patch)
        except Exception:
            logger.exception("Failed to update calendar event id=%s", event_id)
            return None

    async def delete_event(self, event_id: str) -> bool:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _del():
            service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
            return True

        try:
            return await loop.run_in_executor(None, _del)
        except Exception:
            logger.exception("Failed to delete calendar event id=%s", event_id)
            return False
