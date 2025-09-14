import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class EmailIntegrationError(Exception):
    pass


class EmailClientInterface(ABC):
    """Abstract async email client interface used by higher-level services."""

    @abstractmethod
    async def authorize(self, **kwargs) -> Any:
        """Perform any interactive/async authorization (OAuth flows)."""
        raise NotImplementedError

    @abstractmethod
    async def send_message(
        self,
        to: Union[str, List[str]],
        subject: str,
        body_text: str,
        html: Optional[str] = None,
        thread_id: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send a message and return provider response metadata."""
        raise NotImplementedError

    @abstractmethod
    async def list_messages(self, query: Optional[str] = None, max_results: int = 50) -> List[Dict[str, Any]]:
        """List messages (lightweight metadata)."""
        raise NotImplementedError

    @abstractmethod
    async def get_message(self, message_id: str, format: str = "full") -> Optional[Dict[str, Any]]:
        """Fetch raw message data from provider."""
        raise NotImplementedError

    @abstractmethod
    def parse_message_payload(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Parse provider-specific message payload into normalized dict."""
        raise NotImplementedError


def create_email_client(cfg: Dict[str, Any]) -> EmailClientInterface:
    """
    Factory to create a provider-backed email client.
    cfg example:
      { "type": "gmail", "client_secrets_path": "...", "token_path": "..." }
      { "type": "outlook", "email": "me@example.com", "username": "...", "password": "..." }
    """
    provider = (cfg or {}).get("type", "").lower()
    if provider == "gmail":
        try:
            from .gmail_client import GmailClient  # local import to avoid heavy deps at module import time
        except Exception as e:
            logger.exception("Failed to import GmailClient")
            raise EmailIntegrationError("gmail client not available") from e
        return GmailClient(
            client_secrets_path=cfg.get("client_secrets_path"),
            token_path=cfg.get("token_path"),
            scopes=cfg.get("scopes"),
            credentials=cfg.get("credentials"),
        )
    if provider in ("outlook", "exchange", "ews"):
        try:
            from .outlook_client import OutlookClient
        except Exception as e:
            logger.exception("Failed to import OutlookClient")
            raise EmailIntegrationError("outlook client not available") from e
        return OutlookClient(
            email=cfg.get("email"),
            username=cfg.get("username"),
            password=cfg.get("password"),
            server=cfg.get("server"),
            credentials=cfg.get("credentials"),
            autodiscover=cfg.get("autodiscover", True),
        )

    raise EmailIntegrationError(f"unsupported email provider type: {provider}")


# Adapter helpers to normalize calls across providers
async def send(
    client: EmailClientInterface,
    to: Union[str, List[str]],
    subject: str,
    body_text: str,
    html: Optional[str] = None,
    thread_id: Optional[str] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Small helper that normalizes recipient shapes and calls client.send_message.
    """
    # ensure list/list-like where appropriate
    to_arg: Union[str, List[str]]
    if isinstance(to, list):
        # some clients expect a single string for 'to' (gmail) and some expect list (outlook)
        to_arg = to if len(to) > 1 else to[0]
    else:
        to_arg = to

    # call provider; keep exceptions bubbling to caller (or translate as EmailIntegrationError)
    try:
        return await client.send_message(to=to_arg, subject=subject, body_text=body_text, html=html, thread_id=thread_id, cc=cc, bcc=bcc)
    except Exception as exc:
        logger.exception("Email send failed")
        raise EmailIntegrationError(str(exc)) from exc
