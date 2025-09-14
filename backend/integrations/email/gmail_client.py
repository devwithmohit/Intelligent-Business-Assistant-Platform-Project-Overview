import asyncio
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from googleapiclient.discovery import build  # type: ignore

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]


class GmailClient:
    """
    Minimal Gmail client wrapper using google-api-python-client + oauthlib.
    Provides async wrappers around the most common operations:
      - authorize (local server flow) and persist token
      - send_message
      - list_messages
      - get_message
      - parse_message
    Note: network / google client calls are executed in a threadpool to avoid blocking the event loop.
    """

    def __init__(
        self,
        client_secrets_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        credentials: Optional[Credentials] = None,
    ) -> None:
        self.client_secrets_path = client_secrets_path
        self.token_path = token_path
        self.scopes = scopes or GMAIL_SCOPES
        self._creds = credentials
        self._service = None

    # --- auth helpers ---
    async def authorize_via_local_server(self, host: str = "localhost", port: int = 0, open_browser: bool = True) -> Credentials:
        """
        Run InstalledAppFlow.run_local_server in threadpool to obtain credentials and optionally save them.
        """
        if not self.client_secrets_path:
            raise ValueError("client_secrets_path required for OAuth authorization")

        loop = asyncio.get_running_loop()

        def _flow():
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_path, self.scopes)
            creds = flow.run_local_server(host=host, port=port, open_browser=open_browser)
            # persist token if requested
            if self.token_path:
                from pathlib import Path

                try:
                    p = Path(self.token_path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with p.open("w", encoding="utf-8") as fh:
                        fh.write(creds.to_json())
                except Exception:
                    logger.debug("Failed to save token to %s", self.token_path, exc_info=True)
            return creds

        creds = await loop.run_in_executor(None, _flow)
        self._creds = creds
        self._service = None
        return creds

    async def load_credentials_from_token(self) -> Optional[Credentials]:
        """Load saved token JSON from token_path (if set) and refresh if needed."""
        if not self.token_path:
            return None
        loop = asyncio.get_running_loop()

        def _load():
            try:
                import json
                from pathlib import Path

                p = Path(self.token_path)
                if not p.exists():
                    return None
                data = json.loads(p.read_text(encoding="utf-8"))
                creds = Credentials.from_authorized_user_info(data, scopes=self.scopes)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                return creds
            except Exception:
                logger.debug("Failed to load/refresh credentials from %s", self.token_path, exc_info=True)
                return None

        creds = await loop.run_in_executor(None, _load)
        if creds:
            self._creds = creds
        return creds

    # --- internal service factory ---
    async def _get_service(self):
        """Return a built gmail service, building it in threadpool if necessary."""
        if self._service:
            return self._service
        # ensure credentials available/valid
        if not self._creds:
            await self.load_credentials_from_token()
        if not self._creds:
            raise RuntimeError("No credentials available; call authorize_via_local_server or provide credentials/token")

        loop = asyncio.get_running_loop()

        def _build():
            return build("gmail", "v1", credentials=self._creds)

        self._service = await loop.run_in_executor(None, _build)
        return self._service

    # --- message helpers ---
    @staticmethod
    def _create_mime_message(to: str, subject: str, body_text: str, html: Optional[str] = None) -> bytes:
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        text_part = MIMEText(body_text, "plain")
        msg.attach(text_part)
        if html:
            html_part = MIMEText(html, "html")
            msg.attach(html_part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        return raw.encode("ascii")

    async def send_message(self, to: str, subject: str, body_text: str, html: Optional[str] = None, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Send a message. Returns the Gmail API response dict.
        """
        service = await self._get_service()
        raw = self._create_mime_message(to=to, subject=subject, body_text=body_text, html=html).decode("ascii")
        body = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id

        loop = asyncio.get_running_loop()

        def _send():
            return service.users().messages().send(userId="me", body=body).execute()

        try:
            resp = await loop.run_in_executor(None, _send)
            return resp
        except Exception as e:
            logger.exception("Failed to send gmail message to=%s: %s", to, e)
            raise

    async def list_messages(self, query: Optional[str] = None, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        List messages for authenticated user. Returns list of message metadata dicts.
        query: Gmail search query string.
        """
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _list():
            req = service.users().messages().list(userId="me", q=query, maxResults=max_results)
            resp = req.execute()
            return resp.get("messages", []) if isinstance(resp, dict) else []

        try:
            msgs = await loop.run_in_executor(None, _list)
            return msgs
        except Exception as e:
            logger.exception("Failed to list gmail messages: %s", e)
            return []

    async def get_message(self, message_id: str, format: str = "full") -> Optional[Dict[str, Any]]:
        """
        Get a single message by id. format can be 'full', 'raw', 'metadata', 'minimal'.
        """
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _get():
            return service.users().messages().get(userId="me", id=message_id, format=format).execute()

        try:
            return await loop.run_in_executor(None, _get)
        except Exception as e:
            logger.exception("Failed to fetch gmail message id=%s: %s", message_id, e)
            return None

    @staticmethod
    def parse_message_payload(msg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract headers and a best-effort text body from a message resource returned by Gmail API.
        Returns: { 'id', 'threadId', 'headers': {...}, 'snippet', 'body_text' }
        """
        out: Dict[str, Any] = {}
        out["id"] = msg.get("id")
        out["threadId"] = msg.get("threadId")
        out["snippet"] = msg.get("snippet")

        headers = {}
        payload = msg.get("payload", {}) or {}
        for h in payload.get("headers", []) or []:
            headers[h.get("name")] = h.get("value")
        out["headers"] = headers

        # find text/plain or fallback to snippet
        body_text = ""
        def _extract_part(p):
            mime_type = p.get("mimeType", "")
            if mime_type == "text/plain" and p.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", errors="ignore")
            # html fallback could be implemented where needed
            return ""

        if payload.get("parts"):
            for part in payload["parts"]:
                text = _extract_part(part)
                if text:
                    body_text = text
                    break
        else:
            # single part
            body_text = _extract_part(payload) or (msg.get("snippet") or "")

        out["body_text"] = body_text
        return out
