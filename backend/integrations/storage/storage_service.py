import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class StorageServiceError(Exception):
    pass


def _create_storage_client(cfg: Dict[str, Any]):
    """
    Lightweight factory for storage clients. Supports 'google_drive'/'google'
    and 'onedrive'/'microsoft' provider types.
    """
    provider = (cfg or {}).get("type", "").lower()
    if provider in ("google_drive", "google", "gdrive"):
        try:
            from .google_drive_client import GoogleDriveClient
        except Exception as e:
            logger.exception("GoogleDriveClient import failed")
            raise StorageServiceError("google drive client not available") from e
        return GoogleDriveClient(
            client_secrets_path=cfg.get("client_secrets_path"),
            token_path=cfg.get("token_path"),
            scopes=cfg.get("scopes"),
            credentials=cfg.get("credentials"),
        )

    if provider in ("onedrive", "microsoft", "msgraph"):
        try:
            from .onedrive_client import OneDriveClient
        except Exception as e:
            logger.exception("OneDriveClient import failed")
            raise StorageServiceError("onedrive client not available") from e
        return OneDriveClient(
            access_token=cfg.get("access_token"),
            client_id=cfg.get("client_id"),
            client_secret=cfg.get("client_secret"),
            tenant_id=cfg.get("tenant_id"),
            drive_id=cfg.get("drive_id"),
            timeout=cfg.get("timeout", 30),
        )

    raise StorageServiceError(f"unsupported storage provider type: {provider}")


class StorageService:
    """
    High-level file storage orchestration.
    - Manage named storage integration configs and cached client instances.
    - Basic ops: list_files, get_file_metadata, download, upload, create_folder, delete.
    - Simple sync helper to copy files/folders between integrations.
    """

    def __init__(self, integrations_cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._cfg: Dict[str, Dict[str, Any]] = integrations_cfg or {}
        self._clients: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        async with self._lock:
            self._cfg[name] = cfg
            if name in self._clients:
                try:
                    del self._clients[name]
                except Exception:
                    logger.debug("Failed to drop cached storage client %s", name)

    async def _create_client(self, name: str):
        cfg = self._cfg.get(name)
        if not cfg:
            raise StorageServiceError(f"integration not found: {name}")
        return _create_storage_client(cfg)

    async def get_client(self, name: str):
        async with self._lock:
            client = self._clients.get(name)
            if client:
                return client
            client = await self._create_client(name)
            self._clients[name] = client
            return client

    async def list_files(self, integration_name: str, path: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            if hasattr(client, "list_files"):
                return await client.list_files(path=path, limit=limit)  # type: ignore
            raise StorageServiceError("list_files not supported by client")
        except Exception as e:
            logger.exception("Failed to list files for %s", integration_name)
            raise StorageServiceError(str(e)) from e

    async def get_file_metadata(self, integration_name: str, file_id: str) -> Optional[Dict[str, Any]]:
        client = await self.get_client(integration_name)
        try:
            return await client.get_file_metadata(file_id)  # type: ignore
        except Exception as e:
            logger.exception("Failed to get metadata %s for %s", file_id, integration_name)
            raise StorageServiceError(str(e)) from e

    async def download_file(self, integration_name: str, file_identifier: str, dest_path: Optional[Union[str, Path]] = None) -> bytes:
        client = await self.get_client(integration_name)
        try:
            return await client.download_file(file_identifier, dest_path=dest_path)  # type: ignore
        except Exception as e:
            logger.exception("Failed to download file %s from %s", file_identifier, integration_name)
            raise StorageServiceError(str(e)) from e

    async def upload_file(self, integration_name: str, local_path: Union[str, Path], dest_path: Optional[str] = None, mime_type: Optional[str] = None, parent_id: Optional[str] = None) -> Dict[str, Any]:
        client = await self.get_client(integration_name)
        try:
            # many clients use different signatures; try common ones
            if hasattr(client, "upload_file"):
                # google: upload_file(file_path, mime_type=None, parent_id=None)
                # onedrive: upload_file(file_path, dest_path)
                if dest_path is not None:
                    return await client.upload_file(local_path, dest_path)  # type: ignore
                return await client.upload_file(local_path, mime_type=mime_type, parent_id=parent_id)  # type: ignore
            raise StorageServiceError("upload_file not supported by client")
        except Exception as e:
            logger.exception("Failed to upload %s to %s", local_path, integration_name)
            raise StorageServiceError(str(e)) from e

    async def create_folder(self, integration_name: str, name: str, parent: Optional[str] = None) -> Dict[str, Any]:
        client = await self.get_client(integration_name)
        try:
            if hasattr(client, "create_folder"):
                return await client.create_folder(name, parent_id=parent)  # type: ignore
            raise StorageServiceError("create_folder not supported by client")
        except Exception as e:
            logger.exception("Failed to create folder %s on %s", name, integration_name)
            raise StorageServiceError(str(e)) from e

    async def delete_item(self, integration_name: str, identifier: str) -> bool:
        client = await self.get_client(integration_name)
        try:
            if hasattr(client, "delete_item"):
                return await client.delete_item(identifier)  # type: ignore
            if hasattr(client, "delete_file"):
                return await client.delete_file(identifier)  # type: ignore
            raise StorageServiceError("delete not supported by client")
        except Exception as e:
            logger.exception("Failed to delete %s on %s", identifier, integration_name)
            raise StorageServiceError(str(e)) from e

    async def sync_between(self, src_integration: str, dst_integration: str, src_path: Optional[str] = None, dst_path: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        """
        Best-effort sync: list files from src_path on src_integration and copy to dst_integration under dst_path.
        Uses temporary files to stream between providers. Returns summary {copied, errors}.
        """
        out = {"copied": 0, "errors": []}
        try:
            src = await self.get_client(src_integration)
            dst = await self.get_client(dst_integration)
            # list files from source
            items = []
            if hasattr(src, "list_files"):
                items = await src.list_files(path=src_path, limit=limit)  # type: ignore
            else:
                raise StorageServiceError("source does not support listing")

            for it in items[:limit]:
                try:
                    # determine identifier and name
                    file_id = it.get("id") or it.get("name") or it.get("fileId")
                    name = it.get("name") or it.get("filename") or file_id
                    # download to temp file
                    with tempfile.NamedTemporaryFile(delete=True) as tmp:
                        data = await self.download_file(src_integration, file_id, dest_path=tmp.name)
                        # ensure data written (some clients already saved to dest_path)
                        if isinstance(data, (bytes, bytearray)):
                            tmp.file.write(data)
                            tmp.file.flush()
                        # compute destination path
                        dest_target = f"{dst_path.rstrip('/')}/{name}" if dst_path else name
                        # upload
                        await self.upload_file(dst_integration, tmp.name, dest_path=dest_target)
                        out["copied"] += 1
                except Exception as e:
                    logger.exception("Failed to copy file %s", it)
                    out["errors"].append({"file": it, "error": str(e)})
            return out
        except Exception as e:
            logger.exception("Storage sync failed from %s to %s", src_integration, dst_integration)
            raise StorageServiceError(str(e)) from e


# module-level singleton
_default_storage_service: Optional[StorageService] = None


def get_storage_service(cfg: Optional[Dict[str, Dict[str, Any]]] = None) -> StorageService:
    global _default_storage_service
    if _default_storage_service is None:
        _default_storage_service = StorageService(integrations_cfg=cfg)
    return _default_storage_service