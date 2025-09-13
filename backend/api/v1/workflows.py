from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.schemas import orchestration_schemas as schemas
from backend.services.workflow_service import get_workflow_service, WorkflowService, WorkflowServiceError

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _svc() -> WorkflowService:
    return get_workflow_service()


@router.get("/", response_model=List[Dict[str, Any]])
async def list_workflows(service: WorkflowService = Depends(_svc)):
    return await service.list_workflows()


@router.post("/", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_workflow(defn: schemas.WorkflowDefinition, service: WorkflowService = Depends(_svc)):
    try:
        return await service.create_workflow(defn)
    except WorkflowServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{name}", response_model=Dict[str, Any])
async def update_workflow(name: str, defn: schemas.WorkflowDefinition, service: WorkflowService = Depends(_svc)):
    if defn.name != name:
        raise HTTPException(status_code=400, detail="definition.name must match path parameter")
    try:
        return await service.update_workflow(defn)
    except WorkflowServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(name: str, service: WorkflowService = Depends(_svc)):
    try:
        await service.delete_workflow(name)
    except WorkflowServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{name}", response_model=schemas.WorkflowDefinition)
async def get_workflow(name: str, service: WorkflowService = Depends(_svc)):
    defn = await service.get_workflow(name)
    if not defn:
        raise HTTPException(status_code=404, detail="workflow not found")
    return defn


@router.post("/{name}/start", response_model=Dict[str, Any])
async def start_workflow(name: str, req: schemas.WorkflowStartRequest, service: WorkflowService = Depends(_svc)):
    if req.workflow_name != name:
        raise HTTPException(status_code=400, detail="workflow_name in body must match path")
    try:
        instance_id = await service.start(workflow_name=name, start_node=req.start_node, initial_context=req.initial_context, metadata=req.metadata)
        return {"instance_id": instance_id}
    except WorkflowServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{name}/run", response_model=Dict[str, Any])
async def run_and_wait(name: str, req: schemas.WorkflowStartRequest, timeout: Optional[float] = Query(None, description="Seconds to wait for completion"), service: WorkflowService = Depends(_svc)):
    if req.workflow_name != name:
        raise HTTPException(status_code=400, detail="workflow_name in body must match path")
    try:
        return await service.run_and_wait(workflow_name=name, start_node=req.start_node, initial_context=req.initial_context, metadata=req.metadata, timeout=timeout)
    except WorkflowServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instances", response_model=Dict[str, Any])
async def list_instances(service: WorkflowService = Depends(_svc)):
    return await service.list_instances()


@router.get("/instances/{instance_id}", response_model=Optional[schemas.WorkflowInstance])
async def get_instance(instance_id: str, service: WorkflowService = Depends(_svc)):
    inst = await service.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="instance not found")
    return inst


@router.post("/instances/{instance_id}/snapshot", response_model=Dict[str, Any])
async def snapshot_instance(instance_id: str, out_dir: Optional[str] = None, service: WorkflowService = Depends(_svc)):
    try:
        path = await service.snapshot_instance(instance_id, out_dir)
        return {"snapshot_path": path}
    except WorkflowServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{name}/visualize", response_model=Dict[str, str])
async def export_visualization(name: str, out_dir: Optional[str] = None, service: WorkflowService = Depends(_svc)):
    try:
        return await service.export_visualization(name, out_dir=out_dir)
    except WorkflowServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
