import asyncio
import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload  # type: ignore

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveClientError(Exception):
    pass


class GoogleDriveClient:
    """
    Async-friendly Google Drive client wrapper.
    - authorize_via_local_server / load_credentials_from_token
    - list_files / get_file_metadata / download_file / upload_file / create_folder / delete_file

    All blocking google-api calls run in an executor.
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
        self.scopes = scopes or DRIVE_SCOPES
        self._creds = credentials
        self._service = None

    async def authorize_via_local_server(self, host: str = "localhost", port: int = 0, open_browser: bool = True) -> Credentials:
        if not self.client_secrets_path:
            raise GoogleDriveClientError("client_secrets_path required for OAuth authorization")

        loop = asyncio.get_running_loop()

        def _flow():
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_path, scopes=self.scopes)
            creds = flow.run_local_server(host=host, port=port, open_browser=open_browser)
            if self.token_path:
                try:
                    Path(self.token_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(self.token_path, "w", encoding="utf-8") as fh:
                        fh.write(creds.to_json())
                except Exception:
                    logger.debug("Failed to save drive token to %s", self.token_path, exc_info=True)
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
                p = Path(self.token_path)
                if not p.exists():
                    return None
                data = json.loads(p.read_text(encoding="utf-8"))
                creds = Credentials.from_authorized_user_info(data, scopes=self.scopes)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                return creds
            except Exception:
                logger.debug("Failed to load/refresh drive credentials from %s", self.token_path, exc_info=True)
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
            raise GoogleDriveClientError("No credentials available; call authorize_via_local_server or provide credentials/token")

        loop = asyncio.get_running_loop()

        def _build():
            return build("drive", "v3", credentials=self._creds)

        self._service = await loop.run_in_executor(None, _build)
        return self._service

    async def list_files(self, query: Optional[str] = None, page_size: int = 100, fields: str = "nextPageToken, files(id, name, mimeType, parents, modifiedTime, size)") -> List[Dict[str, Any]]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _list():
            req = service.files().list(q=query, pageSize=page_size, fields=fields)
            resp = req.execute()
            return resp.get("files", []) if isinstance(resp, dict) else []

        try:
            return await loop.run_in_executor(None, _list)
        except Exception:
            logger.exception("Failed to list Drive files")
            return []

    async def get_file_metadata(self, file_id: str, fields: str = "id, name, mimeType, parents, size, modifiedTime") -> Optional[Dict[str, Any]]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _get():
            return service.files().get(fileId=file_id, fields=fields).execute()

        try:
            return await loop.run_in_executor(None, _get)
        except Exception:
            logger.exception("Failed to get file metadata id=%s", file_id)
            return None

    async def download_file(self, file_id: str, dest_path: Optional[Union[str, Path]] = None) -> bytes:
        """
        Download file bytes. If dest_path provided, save to disk and return bytes saved.
        Otherwise return bytes in-memory.
        """
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _download():
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fd=fh, request=request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            data = fh.getvalue()
            if dest_path:
                p = Path(dest_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            return data

        try:
            return await loop.run_in_executor(None, _download)
        except Exception:
            logger.exception("Failed to download Drive file id=%s", file_id)
            raise GoogleDriveClientError("download failed")

    async def upload_file(self, file_path: Union[str, Path], mime_type: Optional[str] = None, parent_id: Optional[str] = None) -> Dict[str, Any]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _upload():
            p = Path(file_path)
            metadata = {"name": p.name}
            if parent_id:
                metadata["parents"] = [parent_id]
            media = MediaFileUpload(str(p), mimetype=mime_type or None, resumable=True)
            created = service.files().create(body=metadata, media_body=media, fields="id, name, mimeType, parents").execute()
            return created

        try:
            return await loop.run_in_executor(None, _upload)
        except Exception:
            logger.exception("Failed to upload file %s", file_path)
            raise GoogleDriveClientError("upload failed")

    async def create_folder(self, name: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _create():
            body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                body["parents"] = [parent_id]
            return service.files().create(body=body, fields="id, name, parents").execute()

        try:
            return await loop.run_in_executor(None, _create)
        except Exception:
            logger.exception("Failed to create folder %s", name)
            raise GoogleDriveClientError("create_folder failed")

    async def delete_file(self, file_id: str) -> bool:
        service = await self._get_service()
        loop = asyncio.get_running_loop()

        def _del():
            service.files().delete(fileId=file_id).execute()
            return True

        try:
            return await loop.run_in_executor(None, _del)
        except Exception:
            logger.exception("Failed to delete Drive file id=%s", file_id)
            return False
