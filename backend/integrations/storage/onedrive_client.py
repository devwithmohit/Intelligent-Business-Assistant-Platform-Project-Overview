import asyncio
import aiohttp
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class OneDriveClientError(Exception):
    pass


class OneDriveClient:
    """
    Minimal async OneDrive (Microsoft Graph) client.
    - Supports client credentials flow (client_id/client_secret/tenant) or passing an access_token.
    - Async HTTP via aiohttp.
    - Basic operations: list_files, get_file_metadata, download_file, upload_file (simple PUT), create_folder, delete_item.
    Note: For production use implement robust token refresh, upload sessions for large files, and better error handling.
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        access_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self._token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.drive_id = drive_id  # optional: to target a specific drive (/drives/{drive-id})
        self._token_expires_at: Optional[float] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self.timeout = timeout
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def authorize_client_credentials(self) -> str:
        """
        Obtain access token using client credentials. Requires client_id, client_secret, tenant_id.
        Scopes: use /.default for Microsoft Graph.
        """
        if not (self.client_id and self.client_secret and self.tenant_id):
            raise OneDriveClientError("client_id, client_secret and tenant_id required for client credentials flow")
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
        sess = await self._get_session()
        try:
            async with sess.post(token_url, data=data, timeout=self.timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.exception("Token request failed %s", text)
                    raise OneDriveClientError(f"token request failed: {resp.status} {text}")
                j = await resp.json()
                self._token = j.get("access_token")
                expires_in = j.get("expires_in")
                if expires_in:
                    import time
                    self._token_expires_at = time.time() + int(expires_in) - 30
                return self._token  # type: ignore
        except Exception as exc:
            logger.exception("authorize_client_credentials failed")
            raise OneDriveClientError(str(exc)) from exc

    async def _ensure_token(self) -> None:
        # basic token existence check; for client credentials flow fetch token if missing
        if self._token:
            return
        async with self._lock:
            if self._token:
                return
            await self.authorize_client_credentials()

    def _drive_path_prefix(self) -> str:
        if self.drive_id:
            return f"/drives/{self.drive_id}"
        return "/me/drive"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self._ensure_token()
        sess = await self._get_session()
        url = self.GRAPH_BASE + path
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        try:
            async with sess.request(method, url, headers=headers, timeout=self.timeout, **kwargs) as resp:
                if resp.status in (204, 202):
                    return None
                text = await resp.text()
                try:
                    return json.loads(text) if text else None
                except Exception:
                    return text
        except Exception as exc:
            logger.exception("Graph request failed %s %s", method, path)
            raise OneDriveClientError(str(exc)) from exc

    async def list_files(self, path: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """
        List files under a path. If path is None or '/', list root children.
        path example: "folder/subfolder" (no leading slash).
        """
        try:
            prefix = self._drive_path_prefix()
            if path and path != "/":
                # path-based endpoint
                encoded = aiohttp.helpers.quote(path.strip("/"))
                p = f"{prefix}/root:/{encoded}:/children"
            else:
                p = f"{prefix}/root/children"
            q = f"?$top={limit}"
            resp = await self._request("GET", p + q)
            if isinstance(resp, dict):
                return resp.get("value", []) or []
            return []
        except Exception as exc:
            logger.exception("list_files failed for path=%s", path)
            raise OneDriveClientError(str(exc)) from exc

    async def get_file_metadata(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for an item by id.
        """
        try:
            prefix = self._drive_path_prefix()
            p = f"{prefix}/items/{item_id}"
            return await self._request("GET", p)
        except Exception as exc:
            logger.exception("get_file_metadata failed id=%s", item_id)
            raise OneDriveClientError(str(exc)) from exc

    async def download_file(self, item_identifier: str, dest_path: Optional[Union[str, Path]] = None) -> bytes:
        """
        Download file by item id or by path. If item_identifier contains '/', treats as path.
        If dest_path provided, file is saved to disk and bytes returned.
        """
        try:
            prefix = self._drive_path_prefix()
            if "/" in item_identifier:
                encoded = aiohttp.helpers.quote(item_identifier.strip("/"))
                p = f"{prefix}/root:/{encoded}:/content"
            else:
                p = f"{prefix}/items/{item_identifier}/content"
            await self._ensure_token()
            sess = await self._get_session()
            url = self.GRAPH_BASE + p
            headers = {"Authorization": f"Bearer {self._token}"}
            async with sess.get(url, headers=headers, timeout=self.timeout) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.exception("download_file failed %s", text)
                    raise OneDriveClientError(f"download failed: {resp.status} {text}")
                data = await resp.read()
                if dest_path:
                    pth = Path(dest_path)
                    pth.parent.mkdir(parents=True, exist_ok=True)
                    pth.write_bytes(data)
                return data
        except Exception as exc:
            logger.exception("download_file failed for %s", item_identifier)
            raise OneDriveClientError(str(exc)) from exc

    async def upload_file(self, file_path: Union[str, Path], dest_path: str) -> Dict[str, Any]:
        """
        Upload small file via simple PUT to /root:/path:/content.
        dest_path example: "folder/newname.txt" (no leading slash).
        For large files (>4MB) implement upload session (not implemented here).
        """
        try:
            pth = Path(file_path)
            if not pth.exists():
                raise OneDriveClientError("local file not found")
            data = pth.read_bytes()
            prefix = self._drive_path_prefix()
            encoded = aiohttp.helpers.quote(dest_path.strip("/"))
            path = f"{prefix}/root:/{encoded}:/content"
            sess = await self._get_session()
            await self._ensure_token()
            headers = {"Authorization": f"Bearer {self._token}"}
            async with sess.put(self.GRAPH_BASE + path, data=data, headers=headers, timeout=self.timeout) as resp:
                text = await resp.text()
                if resp.status not in (200, 201):
                    logger.exception("upload_file failed %s", text)
                    raise OneDriveClientError(f"upload failed: {resp.status} {text}")
                try:
                    return json.loads(text)
                except Exception:
                    return {"result": text}
        except Exception as exc:
            logger.exception("upload_file failed %s -> %s", file_path, dest_path)
            raise OneDriveClientError(str(exc)) from exc

    async def create_folder(self, name: str, parent_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a folder under parent_path (None => root).
        """
        try:
            prefix = self._drive_path_prefix()
            if parent_path and parent_path != "/":
                encoded = aiohttp.helpers.quote(parent_path.strip("/"))
                p = f"{prefix}/root:/{encoded}:/children"
            else:
                p = f"{prefix}/root/children"
            body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
            return await self._request("POST", p, json=body)
        except Exception as exc:
            logger.exception("create_folder failed name=%s parent=%s", name, parent_path)
            raise OneDriveClientError(str(exc)) from exc

    async def delete_item(self, item_identifier: str) -> bool:
        """
        Delete item by id or by path (contains '/').
        """
        try:
            prefix = self._drive_path_prefix()
            if "/" in item_identifier:
                encoded = aiohttp.helpers.quote(item_identifier.strip("/"))
                p = f"{prefix}/root:/{encoded}:"
            else:
                p = f"{prefix}/items/{item_identifier}"
            await self._request("DELETE", p)
            return True
        except Exception as exc:
            logger.exception("delete_item failed %s", item_identifier)
            raise OneDriveClientError(str(exc)) from exc
