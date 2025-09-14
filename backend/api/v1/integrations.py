from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from ...services.integration_manager import get_integration_manager, IntegrationManager, IntegrationManagerError
from ...schemas.integration_schemas import parse_integration_config

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


async def _manager() -> IntegrationManager:
    return get_integration_manager()


@router.get("/", summary="List integrations")
async def list_integrations(manager: IntegrationManager = Depends(_manager)) -> Dict[str, Dict[str, Any]]:
    return await manager.list_integrations()


@router.get("/{name}", summary="Get integration config")
async def get_integration(name: str, manager: IntegrationManager = Depends(_manager)) -> Dict[str, Any]:
    cfg = await manager.get_config(name)
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
    return cfg


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create or update an integration")
async def create_integration(payload: Dict[str, Any] = Body(...), manager: IntegrationManager = Depends(_manager)):
    # Validate/normalize config where possible
    try:
        parsed = parse_integration_config(payload)
    except Exception:
        parsed = None

    name = payload.get("name") or (getattr(parsed, "name", None) if parsed is not None else None)
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="integration 'name' is required in payload")

    cfg = payload.copy()
    # ensure name is present in stored config
    cfg["name"] = name

    try:
        await manager.register_integration(name, cfg)
    except IntegrationManagerError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return {"name": name, "config": cfg}


@router.put("/{name}", summary="Update an existing integration")
async def update_integration(name: str, payload: Dict[str, Any] = Body(...), manager: IntegrationManager = Depends(_manager)):
    # merge incoming payload into existing config (replace by default)
    cfg = payload.copy()
    cfg["name"] = name
    try:
        await manager.register_integration(name, cfg)
    except IntegrationManagerError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"name": name, "config": cfg}


@router.delete("/{name}", summary="Delete an integration")
async def delete_integration(name: str, manager: IntegrationManager = Depends(_manager)):
    # remove stored config (best-effort)
    try:
        cfg = await manager.get_config(name)
        if cfg is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
        # mutate internal store under lock
        async with manager._lock:
            manager._cfg.pop(name, None)
            if name in manager._cfg:
                # defensive: if still present fail
                raise RuntimeError("failed to delete integration")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"deleted": True, "name": name}