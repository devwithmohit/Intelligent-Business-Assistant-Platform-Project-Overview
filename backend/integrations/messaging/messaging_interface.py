import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MessagingIntegrationError(Exception):
    pass


class MessagingClientInterface(ABC):
    """Abstract async messaging client interface used by higher-level services."""

    @abstractmethod
    async def send_message(
        self,
        channel: Optional[str] = None,
        text: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def send_direct_message(
        self, user_id: str, text: str, **kwargs
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def list_conversations(self, **kwargs) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def post_ephemeral(
        self, channel: str, user: str, text: str
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


def create_messaging_client(cfg: Dict[str, Any]) -> MessagingClientInterface:
    """
    Factory to create a provider-backed messaging client.
    cfg examples:
      { "type": "slack", "token": "xoxb-...", "default_channel": "C123..." }
      { "type": "teams", "webhook_url": "https://...", "access_token": "..." }
    """
    provider = (cfg or {}).get("type", "").lower()
    if provider == "slack":
        try:
            from .slack_client import SlackClient  # local import
        except Exception as e:
            logger.exception("Failed to import SlackClient")
            raise MessagingIntegrationError("slack client not available") from e
        return SlackClient(
            token=cfg.get("token"), default_channel=cfg.get("default_channel")
        )
    if provider in ("teams", "msteams"):
        try:
            from .teams_client import TeamsClient  # local import
        except Exception as e:
            logger.exception("Failed to import TeamsClient")
            raise MessagingIntegrationError("teams client not available") from e
        return TeamsClient(
            webhook_url=cfg.get("webhook_url"),
            access_token=cfg.get("access_token"),
            default_team_id=cfg.get("default_team_id"),
            default_channel_id=cfg.get("default_channel_id"),
        )

    raise MessagingIntegrationError(f"unsupported messaging provider type: {provider}")


# small adapter helpers -----------------------------------------------------
async def broadcast(
    client: MessagingClientInterface,
    channels: List[str],
    text: str,
    subject: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Send the same message to multiple channels (best-effort)."""
    results: List[Dict[str, Any]] = []
    for ch in channels:
        try:
            res = await client.send_message(channel=ch, text=text, subject=subject)
            results.append({"channel": ch, "result": res})
        except Exception as exc:
            logger.exception("broadcast failed for channel=%s", ch)
            results.append({"channel": ch, "error": str(exc)})
    return results


async def notify_user(
    client: MessagingClientInterface,
    user_id: str,
    text: str,
    subject: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify a user via direct message where supported; fall back to posting to a default channel mentioning the user."""
    try:
        return await client.send_direct_message(
            user_id=user_id, text=text, subject=subject
        )
    except Exception:
        logger.debug(
            "send_direct_message failed, attempting channel mention fallback for user=%s",
            user_id,
        )
        try:
            mention = f"<@{user_id}> {text}"
            return await client.send_message(text=mention, subject=subject)
        except Exception as exc:
            logger.exception("notify_user fallback failed for %s", user_id)
            raise MessagingIntegrationError(str(exc)) from exc
