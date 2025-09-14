import asyncio
import logging
from typing import Any, Dict, Optional

from ..integrations.email.email_service import get_email_service
from ..integrations.calendar.calendar_service import get_calendar_service
from ..integrations.storage.storage_service import get_storage_service
from ..integrations.crm.crm_sync_service import get_crm_sync_service
from ..integrations.messaging.notification_service import get_notification_service
from ..services.kb_manager import get_kb_manager

logger = logging.getLogger(__name__)


class IntegrationManagerError(Exception):
    pass


class IntegrationManager:
    """
    Central registry for third-party integrations.
    - store integration configs
    - route registration to provider-specific service (email/calendar/storage/crm/messaging/kb)
    - return the service handler for a named integration so callers can operate on it
    """

    def __init__(self) -> None:
        self._cfg: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        """
        Register or update an integration config. Routes to provider service register hooks when available.
        """
        async with self._lock:
            self._cfg[name] = cfg or {}
            provider = (cfg or {}).get("type", "").lower()
            try:
                if provider == "gmail" or provider in ("outlook", "exchange", "ews"):
                    svc = get_email_service()
                    await svc.register_integration(name, cfg)
                elif provider in ("google", "calendar", "google_calendar"):
                    svc = get_calendar_service()
                    await svc.register_integration(name, cfg)
                elif provider in (
                    "google_drive",
                    "onedrive",
                    "storage",
                    "gdrive",
                    "microsoft",
                ):
                    svc = get_storage_service()
                    await svc.register_integration(name, cfg)
                elif provider in ("salesforce", "hubspot", "crm"):
                    svc = get_crm_sync_service()
                    await svc.register_integration(name, cfg)
                elif provider in ("slack", "teams", "msteams", "messaging"):
                    svc = get_notification_service()
                    await svc.register_integration(name, cfg)
                elif provider in ("kb", "chroma", "vector_db"):
                    # KB manager uses kb_manager.add_documents / create_kb etc.
                    # store config only; KB manager itself is not an "integration" in the same sense
                    pass
                else:
                    # unknown provider: still store config for custom handling
                    logger.debug(
                        "register_integration: stored unknown provider type=%s name=%s",
                        provider,
                        name,
                    )
            except Exception as exc:
                logger.exception("register_integration failed for %s", name)
                raise IntegrationManagerError(str(exc)) from exc

    async def get_config(self, name: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            return self._cfg.get(name)

    async def list_integrations(self) -> Dict[str, Dict[str, Any]]:
        async with self._lock:
            return dict(self._cfg)

    async def get_handler(self, name: str) -> Any:
        """
        Return the provider-specific service handler responsible for the named integration.
        For messaging/email/calendar/storage/crm this returns the higher-level service instance
        (EmailService/NotificationService/CalendarService/StorageService/CRMSyncService).
        Callers should then use that service's public methods (e.g. send_email, list_events, list_files).
        """
        cfg = await self.get_config(name)
        if not cfg:
            raise IntegrationManagerError(f"integration not found: {name}")
        provider = (cfg or {}).get("type", "").lower()
        if provider in ("gmail", "outlook", "exchange", "ews"):
            return get_email_service()
        if provider in ("google", "calendar", "google_calendar"):
            return get_calendar_service()
        if provider in ("google_drive", "onedrive", "storage", "gdrive", "microsoft"):
            return get_storage_service()
        if provider in ("salesforce", "hubspot", "crm"):
            return get_crm_sync_service()
        if provider in ("slack", "teams", "msteams", "messaging"):
            return get_notification_service()
        if provider in ("kb", "chroma", "vector_db"):
            return get_kb_manager()
        # fallback: return raw config for custom handling
        return cfg


# module-level singleton
_default_integration_manager: Optional[IntegrationManager] = None


def get_integration_manager() -> IntegrationManager:
    global _default_integration_manager
    if _default_integration_manager is None:
        _default_integration_manager = IntegrationManager()
    return _default_integration_manager


# convenience wrappers -------------------------------------------------------
async def register_integration(name: str, cfg: Dict[str, Any]) -> None:
    await get_integration_manager().register_integration(name, cfg)


async def get_integration_handler(name: str) -> Any:
    return await get_integration_manager().get_handler(name)



