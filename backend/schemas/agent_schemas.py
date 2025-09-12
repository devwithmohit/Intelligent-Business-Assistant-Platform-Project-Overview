from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepModel(BaseModel):
    """
    Single step in an agent plan.
    Mirrors backend.agents.interfaces.Step
    """
    type: str = Field(..., example="llm")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """
    Lightweight config blob passed to agent instances.
    Agents may extend with agent-specific fields.
    """
    model_hint: Optional[str] = Field(None, example="deeps-embed-1")
    tools: Optional[List[str]] = Field(default_factory=list)
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AgentCreateRequest(BaseModel):
    """
    Request to create/instantiate an agent.
    """
    agent_type: str = Field(..., example="customer_service")
    name: Optional[str] = Field(None, example="support-bot")
    config: Optional[AgentConfig] = None


class AgentRunRequest(BaseModel):
    """
    Generic run request for an agent. payload is agent-specific.
    """
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)
    sync: Optional[bool] = Field(False, description="If true, run synchronously (blocking) in caller")


class AgentResultModel(BaseModel):
    success: bool = Field(..., example=True)
    output: Optional[str] = Field(None)
    data: Optional[Dict[str, Any]] = Field(default_factory=dict)
    error: Optional[str] = Field(None)


class AgentStatus(BaseModel):
    id: str
    name: str
    agent_type: Optional[str] = None
    running: bool = False
    last_run_at: Optional[datetime] = None
    last_result: Optional[AgentResultModel] = None


class AgentListItem(BaseModel):
    id: str
    name: str
    agent_type: Optional[str] = None
    running: bool = False


class AgentListResponse(BaseModel):
    agents: List[AgentListItem] = Field(default_factory=list)
