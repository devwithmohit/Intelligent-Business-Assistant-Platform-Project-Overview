import asyncio
import logging
from typing import Any, Dict, List, Optional

try:
    from slack_sdk.web.async_client import AsyncWebClient  # type: ignore
    from slack_sdk.errors import SlackApiError  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    AsyncWebClient = None  # type: ignore
    SlackApiError = Exception  # type: ignore

logger = logging.getLogger(__name__)


class SlackClientError(Exception):
    pass


class SlackClient:
    """
    Async wrapper around slack_sdk.AsyncWebClient for common messaging operations.
    - token: bot or user token with chat:write and channels:read scopes
    """

    def __init__(self, token: str, default_channel: Optional[str] = None, timeout: int = 30) -> None:
        if AsyncWebClient is None:
            raise SlackClientError("slack-sdk not installed")
        self._client = AsyncWebClient(token=token, run_async=True, timeout=timeout)
        self.default_channel = default_channel

    async def send_message(
        self,
        channel: Optional[str] = None,
        text: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Post a message to a channel or user conversation.
        channel: channel id or user id (if posting via im.open or using @user in app context)
        Returns Slack API response dict.
        """
        if channel is None:
            channel = self.default_channel
        if not channel:
            raise SlackClientError("channel is required")

        try:
            resp = await self._client.chat_postMessage(
                channel=channel, text=text or "", blocks=blocks, attachments=attachments, thread_ts=thread_ts
            )
            return dict(resp.data or {})
        except SlackApiError as exc:
            logger.exception("Slack chat_postMessage failed for channel=%s", channel)
            raise SlackClientError(str(exc)) from exc

    async def send_direct_message(self, user_id: str, text: str, blocks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Send a DM to a user (opens IM if needed). Returns API response.
        """
        try:
            # Conversations.open is recommended to ensure IM exists; many workspaces allow posting directly to user_id
            open_resp = await self._client.conversations_open(users=[user_id])
            channel = open_resp.data.get("channel", {}).get("id")
            if not channel:
                raise SlackClientError("failed to open DM channel")
            return await self.send_message(channel=channel, text=text, blocks=blocks)
        except SlackApiError as exc:
            logger.exception("Failed to send DM to user=%s", user_id)
            raise SlackClientError(str(exc)) from exc

    async def list_conversations(self, types: str = "public_channel,private_channel,im,mpim", limit: int = 200) -> List[Dict[str, Any]]:
        """
        List conversations the bot/user can see.
        """
        out: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        try:
            while True:
                resp = await self._client.conversations_list(types=types, limit=limit, cursor=cursor)
                data = resp.data or {}
                out.extend(data.get("channels", []) or data.get("conversations", []))
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            return out
        except SlackApiError as exc:
            logger.exception("conversations_list failed")
            raise SlackClientError(str(exc)) from exc

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """
        Return user profile/info dict.
        """
        try:
            resp = await self._client.users_info(user=user_id)
            return dict(resp.data or {})
        except SlackApiError as exc:
            logger.exception("users_info failed for %s", user_id)
            raise SlackClientError(str(exc)) from exc

    async def post_ephemeral(self, channel: str, user: str, text: str) -> Dict[str, Any]:
        """
        Post an ephemeral message visible only to a user.
        """
        try:
            resp = await self._client.chat_postEphemeral(channel=channel, user=user, text=text)
            return dict(resp.data or {})
        except SlackApiError as exc:
            logger.exception("chat_postEphemeral failed for channel=%s user=%s", channel, user)
            raise SlackClientError(str(exc)) from exc

    async def close(self) -> None:
        """
        Close underlying client (best-effort). AsyncWebClient has no explicit close but we attempt to close transport.
        """
        try:
            transport = getattr(self._client, "api_call", None)
            # nothing standard to close; rely on garbage collection. Provide hook for future.
            return None
        except Exception:
            logger.debug("SlackClient.close() had nothing to do")

# convenience factory/singleton ------------------------------------------------
_default_slack_client: Optional[SlackClient] = None


def get_slack_client(token: Optional[str] = None, default_channel: Optional[str] = None) -> SlackClient:
    """
    Return a singleton SlackClient. If token is omitted, will attempt to reuse existing instance.
    """
    global _default_slack_client
    if _default_slack_client is None:
        if not token:
            raise SlackClientError("token required to create SlackClient")
        _default_slack_client = SlackClient(token=token, default_channel=default_channel)
    return _default_slack_client
