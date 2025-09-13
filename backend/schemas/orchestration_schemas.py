from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class WorkflowNode(BaseModel):
    id: str = Field(..., description="Unique node id within the workflow")
    agent: str = Field(..., description="Agent name responsible for this node")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Node-specific configuration passed to the agent")
    description: Optional[str] = Field(None, description="Human-friendly node description")


class WorkflowEdge(BaseModel):
    src: str = Field(..., description="Source node id")
    dst: str = Field(..., description="Destination node id")
    condition: Optional[str] = Field(None, description="Optional boolean expression string evaluated against the workflow context")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional edge metadata")


class WorkflowDefinition(BaseModel):
    name: str = Field(..., description="Workflow name / identifier")
    agents: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Registered agents and their metadata")
    nodes: List[WorkflowNode] = Field(default_factory=list, description="Workflow nodes")
    edges: List[WorkflowEdge] = Field(default_factory=list, description="Directed edges between nodes")


class WorkflowCreateRequest(BaseModel):
    name: Optional[str] = Field(None, description="Optional name. If omitted one may be generated")
    definition: WorkflowDefinition = Field(..., description="Workflow definition payload")


class WorkflowStartRequest(BaseModel):
    workflow_name: str = Field(..., description="Name of workflow to start")
    start_node: str = Field(..., description="Node id to start execution from")
    initial_context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Initial context to seed the workflow")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional metadata for the instance")


class WorkflowInstance(BaseModel):
    id: str = Field(..., description="Instance id")
    workflow_name: str = Field(..., description="Associated workflow name")
    context: Dict[str, Any] = Field(default_factory=dict, description="Current workflow context")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Instance metadata (errors, status, etc.)")
    created_at: float = Field(..., description="Unix timestamp created")
    updated_at: float = Field(..., description="Unix timestamp last updated")


class HandoffInstruction(BaseModel):
    handoff_to_node: Optional[Union[str, List[str]]] = Field(
        None, description="Optional explicit next node id or list of node ids to hand off to"
    )


class AgentExecutionResult(BaseModel):
    context_updates: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Partial context to merge into instance")
    handoff_to_node: Optional[Union[str, List[str]]] = Field(None, description="Optional handoff override")
    status: str = Field("ok", description="Execution status: 'ok' or 'error'")
    detail: Optional[str] = Field(None, description="Optional diagnostic message")
