from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, TypedDict, Union, runtime_checkable


class Step(TypedDict, total=False):
    """
    Shape for a single plan step produced by agents.
    - type: a short string describing the step (e.g. "llm", "tool", "http")
    - payload: provider-specific data for executing the step
    """
    type: str
    payload: Dict[str, Any]


class AgentResult(Dict[str, Any]):
    """
    Lightweight result shape for agent runs.
    Keys commonly used: success(bool), output(str), error(optional str), data(optional dict)
    """
    pass


ToolSync = Callable[..., Any]
ToolAsync = Callable[..., Awaitable[Any]]
ToolCallable = Union[ToolSync, ToolAsync]


@runtime_checkable
class Tool(Protocol):
    """
    Tool protocol. Implementations may be sync or async callables.
    A tool may optionally expose metadata attributes.
    """
    name: str
    description: Optional[str]

    def __call__(self, *args: Any, **kwargs: Any) -> Union[Any, Awaitable[Any]]:
        ...


@runtime_checkable
class Observer(Protocol):
    """
    Observer hooks for agent lifecycle / events.
    Implement on_event to receive notifications: on_event(agent_id, event_name, payload).
    """
    def on_event(self, agent_id: str, event_name: str, payload: Optional[Dict[str, Any]] = None) -> None:
        ...


class AgentProtocol(Protocol):
    """
    Protocol describing the public surface of an Agent.
    Matches BaseAgent: start/stop/run/ cancel/ is_running and basic helpers.
    """

    id: str
    name: str
    config: Dict[str, Any]

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def run(self, **kwargs: Any) -> AgentResult:
        ...

    def cancel(self) -> None:
        ...

    def is_running(self) -> bool:
        ...

    async def _plan(self, **kwargs: Any) -> List[Step]:
        ...

    async def _execute_step(self, step: Step, **kwargs: Any) -> Any:
        ...


# Registry typing helpers
AgentFactoryCallable = Callable[[str, Optional[Dict[str, Any]]], AgentProtocol]
