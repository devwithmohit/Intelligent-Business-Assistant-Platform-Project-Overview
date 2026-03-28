import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from .graph_builder import GraphBuilder
from .routing_logic import route_and_execute, AgentRunner, RoutingError
from .state_management import StateManager, get_state_manager

logger = logging.getLogger(__name__)


class WorkflowExecutorError(Exception):
    pass


class WorkflowExecutor:
    """
    Lightweight async workflow executor for GraphBuilder workflows.

    Usage:
      exec = WorkflowExecutor()
      instance_id = await exec.start(graph, start_node="start", initial_context={"q": "hello"})
      final_state = await exec.wait_for_complete(instance_id)
    """

    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        agent_runner: Optional[AgentRunner] = None,
        max_steps: int = 500,
        step_timeout: float = 20.0,
    ):
        self.state_manager = state_manager or get_state_manager()
        self.agent_runner = agent_runner or AgentRunner()
        self.max_steps = max_steps
        self.step_timeout = step_timeout

    async def start(
        self,
        graph: GraphBuilder,
        start_node: str,
        initial_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a new workflow instance and begin execution from start_node.
        Returns instance_id.
        """
        st = await self.state_manager.create_instance(
            workflow_name=graph.name,
            initial_context=initial_context or {},
            metadata=metadata or {},
        )
        instance_id = st.id
        # schedule background run (fire-and-forget)
        asyncio.create_task(self._run_instance(instance_id, graph, [start_node]))
        logger.info(
            "Started workflow instance %s graph=%s start_node=%s",
            instance_id,
            graph.name,
            start_node,
        )
        return instance_id

    async def _run_instance(
        self, instance_id: str, graph: GraphBuilder, entry_nodes: List[str]
    ) -> None:
        queue = list(entry_nodes)
        steps = 0
        start_ts = time.time()
        try:
            while queue and steps < self.max_steps:
                if not queue:
                    break
                next_queue: List[str] = []
                # execute nodes in series to preserve ordering; callers can run multiple instances concurrently
                for node in queue:
                    try:
                        # enforce per-node timeout
                        resolved = await asyncio.wait_for(
                            route_and_execute(
                                instance_id,
                                node,
                                graph,
                                self.state_manager,
                                self.agent_runner,
                            ),
                            timeout=self.step_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Node execution timed out instance=%s node=%s",
                            instance_id,
                            node,
                        )
                        await self.state_manager.update_instance(
                            instance_id,
                            {"metadata": {"last_error": f"timeout at node {node}"}},
                        )
                        continue
                    except Exception as e:
                        logger.exception(
                            "Error routing/executing node %s for instance %s: %s",
                            node,
                            instance_id,
                            e,
                        )
                        await self.state_manager.update_instance(
                            instance_id, {"metadata": {"last_error": str(e)}}
                        )
                        continue
                    # append resolved next nodes
                    for n in resolved:
                        if n not in next_queue:
                            next_queue.append(n)
                queue = next_queue
                steps += 1
            if steps >= self.max_steps:
                logger.warning(
                    "Max steps reached for instance %s (max_steps=%d)",
                    instance_id,
                    self.max_steps,
                )
                await self.state_manager.update_instance(
                    instance_id, {"metadata": {"last_error": "max_steps_exceeded"}}
                )
        except Exception:
            logger.exception(
                "Unhandled error in workflow executor for instance %s", instance_id
            )
            await self.state_manager.update_instance(
                instance_id,
                {"metadata": {"last_error": "executor_unhandled_exception"}},
            )
        finally:
            dur = time.time() - start_ts
            logger.info(
                "Workflow instance %s finished after %.2fs steps=%d",
                instance_id,
                dur,
                steps,
            )

    async def run_and_wait(
        self,
        graph: GraphBuilder,
        start_node: str,
        initial_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        poll_interval: float = 0.5,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Convenience: start workflow and wait until it completes (no outstanding nodes)
        or timeout is reached. Returns final WorkflowState as dict.
        """
        instance_id = await self.start(
            graph,
            start_node=start_node,
            initial_context=initial_context,
            metadata=metadata,
        )
        return await self.wait_for_complete(
            instance_id, poll_interval=poll_interval, timeout=timeout
        )

    async def wait_for_complete(
        self,
        instance_id: str,
        poll_interval: float = 0.5,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Poll state until executor marks no further changes (best-effort).
        Completion heuristic: no updates to updated_at for a short window and no queued nodes.
        """
        start = time.time()
        last_updated = None
        stable_count = 0
        while True:
            st = await self.state_manager.get_instance(instance_id)
            if st is None:
                raise WorkflowExecutorError("instance not found")
            # consider finished when no recent metadata errors and stable context for a few polls
            if last_updated is None:
                last_updated = st.updated_at
            if st.updated_at == last_updated:
                stable_count += 1
            else:
                stable_count = 0
                last_updated = st.updated_at
            # treat stable_count >= 3 as finished
            if stable_count >= 3:
                return {
                    "id": st.id,
                    "workflow_name": st.workflow_name,
                    "context": st.context,
                    "metadata": st.metadata,
                    "created_at": st.created_at,
                    "updated_at": st.updated_at,
                }
            if timeout and (time.time() - start) > timeout:
                raise WorkflowExecutorError("wait_for_complete timeout")
            await asyncio.sleep(poll_interval)
