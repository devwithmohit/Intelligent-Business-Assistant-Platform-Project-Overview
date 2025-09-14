import asyncio
import logging
from typing import Any, Dict, List, Optional

# optional deps
try:
    import pymsteams  # type: ignore
except Exception:  # pragma: no cover - optional
    pymsteams = None  # type: ignore

try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover - optional
    aiohttp = None  # type: ignore

logger = logging.getLogger(__name__)


class TeamsClientError(Exception):
    pass


class TeamsClient:
    """
    Minimal Microsoft Teams integration helper.

    Two supported modes:
      - incoming webhook (recommended for simple notifications): provide webhook_url or default_webhook
      - Microsoft Graph API (requires access_token): provide access_token and optionally tenant/team/channel ids

    This wrapper provides async-friendly helpers. Where libraries are blocking (pymsteams) we run them
    in a threadpool; where async HTTP is available we use aiohttp.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        access_token: Optional[str] = None,
        default_team_id: Optional[str] = None,
        default_channel_id: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.webhook_url = webhook_url
        self.access_token = access_token
        self.default_team_id = default_team_id
        self.default_channel_id = default_channel_id
        self.timeout = timeout

    # --------------------
    # Webhook-based posting
    # --------------------
    async def send_via_webhook(self, webhook_url: str, text: str, title: Optional[str] = None) -> Dict[str, Any]:
        """
        Post a simple message via incoming webhook URL.
        Returns provider response-like dict.
        """
        if not webhook_url:
            raise TeamsClientError("webhook_url is required for webhook send")

        # prefer aiohttp if available
        if aiohttp is not None:
            async with aiohttp.ClientSession() as sess:
                try:
                    payload = {"text": text}
                    if title:
                        payload["title"] = title
                    async with sess.post(webhook_url, json=payload, timeout=self.timeout) as resp:
                        text_resp = await resp.text()
                        return {"status": resp.status, "text": text_resp}
                except Exception as exc:
                    logger.exception("Webhook send failed")
                    raise TeamsClientError(str(exc)) from exc

        # fallback to pymsteams (blocking) if available
        if pymsteams is None:
            raise TeamsClientError("no http client available (aiohttp) and pymsteams not installed")

        loop = asyncio.get_running_loop()

        def _send():
            try:
                connector = pymsteams.connectorcard(webhook_url)
                if title:
                    connector.title(title)
                connector.text(text)
                connector.send()
                return {"status": 200, "text": "sent"}
            except Exception as exc:
                logger.exception("pymsteams webhook send failed")
                raise

        try:
            return await loop.run_in_executor(None, _send)
        except Exception as exc:
            raise TeamsClientError(str(exc)) from exc

    # --------------------
    # Graph API posting (simple)
    # --------------------
    async def send_via_graph_to_channel(
        self,
        team_id: Optional[str],
        channel_id: Optional[str],
        text: str,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Post a message to a channel using Microsoft Graph chatMessage API.
        Requires access_token with appropriate scopes (ChannelMessage.Send or ChatMessage.Send).
        team_id and channel_id must be provided (or defaults set on client).
        """
        if not self.access_token:
            raise TeamsClientError("access_token required for Graph API send")
        team = team_id or self.default_team_id
        channel = channel_id or self.default_channel_id
        if not team or not channel:
            raise TeamsClientError("team_id and channel_id required for Graph channel message")

        if aiohttp is None:
            raise TeamsClientError("aiohttp required for Graph API calls")

        url = f"https://graph.microsoft.com/v1.0/teams/{team}/channels/{channel}/messages"
        body = {"body": {"contentType": "html", "content": subject + "<br/>" + text if subject else text}}
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=headers) as sess:
            try:
                async with sess.post(url, json=body, timeout=self.timeout) as resp:
                    resp_json = None
                    try:
                        resp_json = await resp.json()
                    except Exception:
                        resp_text = await resp.text()
                        resp_json = {"text": resp_text}
                    return {"status": resp.status, "response": resp_json}
            except Exception as exc:
                logger.exception("Graph API send failed")
                raise TeamsClientError(str(exc)) from exc

    # --------------------
    # Convenience wrapper
    # --------------------
    async def send_message(
        self,
        *,
        webhook_url: Optional[str] = None,
        team_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        text: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        High-level send helper. Chooses webhook if webhook_url (param or default) is available,
        otherwise attempts Graph API posting to channel.
        """
        text = text or ""
        # prefer webhook if available
        webhook = webhook_url or self.webhook_url
        if webhook:
            return await self.send_via_webhook(webhook, text=text, title=subject)
        # otherwise fallback to Graph
        return await self.send_via_graph_to_channel(team_id=team_id, channel_id=channel_id, text=text, subject=subject)

    # --------------------
    # Optional helpers (Graph)
    # --------------------
    async def list_team_channels(self, team_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List channels for a team via Graph API. Requires access_token.
        """
        if not self.access_token:
            raise TeamsClientError("access_token required for Graph API calls")
        if aiohttp is None:
            raise TeamsClientError("aiohttp required for Graph API calls")
        team = team_id or self.default_team_id
        if not team:
            raise TeamsClientError("team_id required")

        url = f"https://graph.microsoft.com/v1.0/teams/{team}/channels"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        async with aiohttp.ClientSession(headers=headers) as sess:
            try:
                async with sess.get(url, timeout=self.timeout) as resp:
                    data = await resp.json()
                    return data.get("value", [])
            except Exception as exc:
                logger.exception("list_team_channels failed")
                raise TeamsClientError(str(exc)) from exc
