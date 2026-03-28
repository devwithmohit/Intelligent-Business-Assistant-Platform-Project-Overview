import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from orchestration.state_management import get_state_manager

from ..services import llm_service, memory_service, tool_service

logger = logging.getLogger("backend.agents.base")


@dataclass
class AgentResult:
    success: bool
    output: Optional[str] = None
    data: Optional[Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None


class BaseAgent(ABC):
    """
    BaseAgent provides shared lifecycle, tooling and memory helpers.
    Subclasses should implement _plan and _execute_step (or override run).
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.id = str(uuid.uuid4())
        self.name = name
        self.config = config or {}
        self._running = False
        self._cancel_event = asyncio.Event()
        self.tools = (
            tool_service.ToolRegistry()
            if hasattr(tool_service, "ToolRegistry")
            else tool_service
        )
        # memory_service expected to expose get_memory / store_memory helpers
        self.memory = memory_service
        # LLM entrypoint (llm_service.generate)
        self.llm = llm_service
        logger.debug(
            "Agent initialized id=%s name=%s config=%s", self.id, self.name, self.config
        )

    async def start(self) -> None:
        """Start agent (non-blocking)."""
        if self._running:
            return
        self._running = True
        self._cancel_event.clear()
        logger.info("Agent starting id=%s name=%s", self.id, self.name)

    async def stop(self) -> None:
        """Signal agent to stop and perform any cleanup."""
        if not self._running:
            return
        logger.info("Agent stopping id=%s name=%s", self.id, self.name)
        self._cancel_event.set()
        self._running = False

    async def run(self, **kwargs) -> AgentResult:
        """
        High-level run method. Subclasses may override.
        Default flow:
          - call start()
          - call _plan(...) to produce steps
          - execute steps via _execute_step
          - store results in memory/audit
        """
        # attach workflow instance if provided
        wf_id = kwargs.get("workflow_instance_id") or kwargs.get("instance_id")
        if wf_id:
            self.attach_workflow(wf_id)

            # attempt to fetch current workflow context and inject for convenience
            try:
                sm = get_state_manager()
                st = await sm.get_instance(wf_id)
                if st:
                    # expose under a named key so agent implementations can opt-in
                    kwargs.setdefault("workflow_context", dict(st.context or {}))
            except Exception:
                logger.debug("Failed to fetch workflow context for %s", wf_id)

        await self.start()
        try:
            plan = await self._plan(**kwargs)
            logger.debug("Agent plan id=%s plan=%s", self.id, plan)
            result = await self._execute_plan(plan, **kwargs)
            # Optionally persist run result to memory/audit
            try:
                await self._save_run_result(result)
            except Exception:
                logger.exception("Failed to save run result for agent=%s", self.name)
            return result
        except asyncio.CancelledError:
            return AgentResult(success=False, error="cancelled")
        except Exception as exc:
            logger.exception("Agent run error id=%s name=%s", self.id, self.name)
            return AgentResult(success=False, error=str(exc))
        finally:
            await self.stop()

    @abstractmethod
    async def _plan(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Produce an ordered list of steps describing work to perform.
        Each step is a dict containing at least a 'type' key.
        """
        raise NotImplementedError

    async def _execute_plan(self, plan: List[Dict[str, Any]], **kwargs) -> AgentResult:
        """
        Default plan executor: iterate steps and call _execute_step for each.
        Subclasses may override for more complex orchestration (parallelism, retries).
        """
        outputs: List[Any] = []
        for idx, step in enumerate(plan):
            if self._cancel_event.is_set():
                logger.info("Agent execution cancelled id=%s at step=%d", self.id, idx)
                return AgentResult(success=False, output="cancelled")
            try:
                out = await self._execute_step(step, **kwargs)
                outputs.append(out)
            except Exception as exc:
                logger.exception("Agent step failed id=%s step=%s", self.id, step)
                return AgentResult(
                    success=False, output=None, error=str(exc), data={"step_index": idx}
                )
        # combine outputs into a single textual summary where possible
        text_out = "\n".join([str(o) for o in outputs if o is not None])
        return AgentResult(success=True, output=text_out, data={"steps": outputs})

    @abstractmethod
    async def _execute_step(self, step: Dict[str, Any], **kwargs) -> Any:
        """
        Execute a single step generated by _plan.
        Step shape is agent-specific (could be LLM call, tool invocation, external API).
        """
        raise NotImplementedError

    # Convenience LLM helper
    async def llm_generate(
        self,
        task: str = "chat",
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        model_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        req = llm_service.LLMRequest(
            task=task,
            prompt=prompt,
            messages=[llm_service.ChatMessage(**m) for m in (messages or [])]
            if messages
            else None,
            model_hint=model_hint,
            params=params,
        )
        resp = await self.llm.generate(req)
        return resp.text if resp and getattr(resp, "text", None) else ""

    # Memory helpers
    async def recall(self, key: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve memory items for this agent/context."""
        try:
            if hasattr(self.memory, "get_memory"):
                return await self.memory.get_memory(
                    agent_id=self.id, key=key, limit=limit
                )
        except Exception:
            logger.exception("Memory recall failed for agent=%s key=%s", self.id, key)
        return []

    async def remember(
        self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Store a memory item for this agent/context."""
        try:
            if hasattr(self.memory, "store_memory"):
                await self.memory.store_memory(
                    agent_id=self.id, key=key, value=value, metadata=metadata or {}
                )
        except Exception:
            logger.exception("Memory store failed for agent=%s key=%s", self.id, key)

    async def call_tool(self, tool_name: str, *args, **kwargs) -> Any:
        """
        Invoke a registered tool via tool_service. Tool implementations should be async or sync.
        """
        try:
            tool = (
                self.tools.get(tool_name)
                if hasattr(self.tools, "get")
                else getattr(self.tools, tool_name, None)
            )
            if tool is None:
                raise RuntimeError(f"tool not found: {tool_name}")
            if asyncio.iscoroutinefunction(tool):
                return await tool(*args, **kwargs)
            # sync call support
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: tool(*args, **kwargs))
        except Exception as exc:
            logger.exception("Tool call failed agent=%s tool=%s", self.name, tool_name)
            raise

    async def _save_run_result(self, result: AgentResult) -> None:
        """Persist run result to memory / audit. Best-effort, non-blocking on failure."""
        try:
            await self.remember(key="last_run", value={"result": result.__dict__})
        except Exception:
            logger.debug("Failed to persist run result for agent=%s", self.name)

    # --- workflow context / state sharing helpers ---
    def attach_workflow(self, instance_id: Optional[str]) -> None:
        """Associate this agent with a workflow instance id for the duration of a run."""
        self._workflow_instance_id = instance_id

    def detach_workflow(self) -> None:
        """Remove workflow association."""
        self._workflow_instance_id = None

    @property
    def workflow_instance_id(self) -> Optional[str]:
        """Return associated workflow instance id, if any."""
        return self._workflow_instance_id

    async def get_workflow_context(self) -> Dict[str, Any]:
        """Fetch current workflow context from the StateManager (best-effort)."""
        if not self._workflow_instance_id:
            return {}
        try:
            sm = get_state_manager()
            st = await sm.get_instance(self._workflow_instance_id)
            return dict(st.context or {}) if st else {}
        except Exception:
            logger.debug(
                "Failed to get workflow context for %s", self._workflow_instance_id
            )
            return {}

    async def update_workflow_context(
        self, updates: Dict[str, Any], merge: bool = True
    ) -> None:
        """
        Update workflow instance context. If merge is True, perform a shallow merge.
        This is best-effort and will not raise on failure.
        """
        if not self._workflow_instance_id:
            return
        try:
            sm = get_state_manager()
            await sm.update_instance(
                self._workflow_instance_id, {"context": updates}, merge=merge
            )
        except Exception:
            logger.exception(
                "Failed to update workflow context for %s", self._workflow_instance_id
            )

    async def set_workflow_metadata(
        self, metadata: Dict[str, Any], merge: bool = True
    ) -> None:
        """Store metadata on the workflow instance (audit, last_agent, etc.)."""
        if not self._workflow_instance_id:
            return
        try:
            sm = get_state_manager()
            await sm.update_instance(
                self._workflow_instance_id, {"metadata": metadata}, merge=merge
            )
        except Exception:
            logger.exception(
                "Failed to set workflow metadata for %s", self._workflow_instance_id
            )

    # Health / status helpers
    def is_running(self) -> bool:
        return self._running

    def cancel(self) -> None:
        """Immediate cancel signal for long running operations."""
        self._cancel_event.set()

    # Simple synchronous wrapper
    def run_sync(self, **kwargs) -> AgentResult:
        """Run agent synchronously (blocking) — convenience for scripts/tests."""
        return asyncio.get_event_loop().run_until_complete(self.run(**kwargs))
