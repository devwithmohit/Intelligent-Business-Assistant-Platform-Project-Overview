import asyncio
import logging
from typing import Any, Dict, List, Optional

from exchangelib import Account, Credentials, Configuration, DELEGATE, Message, HTMLBody  # type: ignore

logger = logging.getLogger(__name__)


class OutlookClient:
    """
    Thin wrapper around exchangelib.Account with async-friendly methods.
    - Provide username/password or pre-built Credentials
    - Async wrappers use loop.run_in_executor to avoid blocking event loop
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
        self._credentials = credentials or (
            Credentials(username, password) if username and password else None
        )
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
                cfg = (
                    Configuration(server=self._server, credentials=self._credentials)
                    if self._credentials
                    else None
                )
            return Account(
                primary_smtp_address=self.email,
                credentials=self._credentials,
                autodiscover=self._autodiscover,
                config=cfg,
                access_type=DELEGATE,
            )

        try:
            self._account = await loop.run_in_executor(None, _build)
            return self._account
        except Exception as exc:
            logger.exception(
                "Failed to initialize Outlook account for %s: %s", self.email, exc
            )
            raise

    async def send_message(
        self,
        to: List[str],
        subject: str,
        body_text: str,
        html: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Send an email. Returns a dict with rudimentary send metadata.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _send():
            msg = Message(
                account=acct,
                folder=acct.sent,
                subject=subject,
                body=HTMLBody(html) if html else body_text,
                to_recipients=to,
                cc_recipients=cc or [],
                bcc_recipients=bcc or [],
            )
            msg.send_and_save()
            return {
                "message_id": str(msg.message_id)
                if getattr(msg, "message_id", None)
                else "",
                "subject": subject,
            }

        try:
            return await loop.run_in_executor(None, _send)
        except Exception:
            logger.exception("Failed to send Outlook message to=%s", to)
            raise

    async def list_messages(
        self, folder: str = "inbox", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List recent messages in a folder. Returns list of lightweight dicts.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _list():
            f = getattr(acct, folder) if hasattr(acct, folder) else acct.inbox
            items = f.all().order_by("-datetime_received")[:limit]
            out = []
            for it in items:
                out.append(
                    {
                        "id": str(getattr(it, "message_id", "")),
                        "subject": getattr(it, "subject", ""),
                        "from": getattr(it, "author", None).email
                        if getattr(it, "author", None)
                        else None,
                        "datetime_received": getattr(it, "datetime_received", None),
                        "is_read": getattr(it, "is_read", False),
                        "snippet": (getattr(it, "text_body", None) or "")[:200],
                    }
                )
            return out

        try:
            return await loop.run_in_executor(None, _list)
        except Exception:
            logger.exception("Failed to list messages for %s", self.email)
            return []

    async def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single message by id. Returns parsed dict or None.
        """
        acct = await self._get_account()
        loop = asyncio.get_running_loop()

        def _get():
            try:
                qs = acct.inbox.filter(message_id=message_id)
                it = qs.first()
                if not it:
                    return None
                return {
                    "id": str(getattr(it, "message_id", "")),
                    "subject": getattr(it, "subject", ""),
                    "from": getattr(it, "author", None).email
                    if getattr(it, "author", None)
                    else None,
                    "to": [r.email for r in getattr(it, "to_recipients", [])],
                    "cc": [r.email for r in getattr(it, "cc_recipients", [])],
                    "datetime_received": getattr(it, "datetime_received", None),
                    "body_text": getattr(it, "text_body", None),
                    "body_html": getattr(it, "html_body", None),
                }
            except Exception:
                logger.exception("Failed to fetch message id=%s", message_id)
                return None

        try:
            return await loop.run_in_executor(None, _get)
        except Exception:
            logger.exception("get_message failed for %s", message_id)
            return None
