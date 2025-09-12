"""
AgentService - orchestrator to create/manage/run agents.

Features:
- create / discover agents via agents.agent_factory.create_agent
- run agents synchronously or asynchronously with optional retries
- lightweight in-process queue worker for submitted jobs
- audit logging into agent memory (if memory_service available)
- track running tasks and allow cancellation
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from ..agents.agent_factory import create_agent, available_agent_types, AgentNotFound
from ..agents.base_agent import BaseAgent, AgentResult
from ..schemas import agent_schemas

logger = logging.getLogger(__name__)

# Module-level singleton
_default_service: Optional["AgentService"] = None


class AgentServiceError(Exception):
    pass


class AgentService:
    def __init__(self) -> None:
        # agent_id -> BaseAgent instance
        self._agents: Dict[str, BaseAgent] = {}
        # agent_id -> asyncio.Task for currently running run() calls
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        # internal job queue for background processing (agent_type, name, config, payload, retries)
        self._queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._stopped = False

    async def start_worker(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._stopped = False
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("AgentService worker started")

    async def stop_worker(self) -> None:
        self._stopped = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("AgentService worker stopped")

    async def _worker_loop(self) -> None:
        while not self._stopped:
            try:
                job = await self._queue.get()
                try:
                    await self._handle_job(job)
                except Exception:
                    logger.exception("AgentService worker failed to handle job: %s", job)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("AgentService worker loop error, sleeping briefly")
                await asyncio.sleep(0.5)

    async def _handle_job(self, job: Dict[str, Any]) -> None:
        agent_type = job.get("agent_type")
        name = job.get("name")
        config = job.get("config")
        payload = job.get("payload", {}) or {}
        retries = int(job.get("retries", 0))
        backoff = float(job.get("backoff", 0.5))

        try:
            agent = await self._ensure_agent(agent_type, name=name, config=config)
        except AgentNotFound:
            logger.error("Job requested unknown agent_type=%s", agent_type)
            return

        attempt = 0
        last_result: Optional[AgentResult] = None
        while attempt <= retries:
            attempt += 1
            try:
                res = await self.run_agent(agent.id, payload=payload, sync=False)
                last_result = res
                if getattr(res, "success", False):
                    break
            except Exception as exc:
                logger.exception("Agent job attempt %d failed for %s: %s", attempt, agent_type, exc)
            if attempt <= retries:
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
        # Persist audit to memory if available
        try:
            await self._persist_audit(agent, payload, last_result)
        except Exception:
            logger.debug("Failed to persist audit after job for agent=%s", getattr(agent, "id", "unknown"))

    async def _ensure_agent(self, agent_type: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> BaseAgent:
        """
        Create or return an existing agent of the same type+name combination.
        """
        # simple dedupe by name if present
        async with self._lock:
            if name:
                for a in self._agents.values():
                    if a.name == name and getattr(a, "config", None) == (config or {}):
                        return a
            # create new agent
            agent = create_agent(agent_type=agent_type, name=name or agent_type, config=config or {})
            self._agents[agent.id] = agent
            logger.info("AgentService created agent id=%s type=%s name=%s", agent.id, agent_type, agent.name)
            return agent

    async def create_agent(self, agent_type: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> BaseAgent:
        return await self._ensure_agent(agent_type, name=name, config=config)

    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        return self._agents.get(agent_id)

    def list_agents(self) -> List[Dict[str, Any]]:
        out = []
        for a in self._agents.values():
            out.append({"id": a.id, "name": a.name, "config": getattr(a, "config", {}), "running": a.is_running()})
        return out

    async def run_agent(self, agent_id: str, payload: Optional[Dict[str, Any]] = None, sync: bool = False, timeout: Optional[float] = None) -> AgentResult:
        """
        Execute agent.run(...) either synchronously (blocking) or asynchronously.
        Returns AgentResult (or raises).
        """
        agent = self.get_agent(agent_id)
        if not agent:
            raise AgentServiceError(f"Agent not found: {agent_id}")

        # if sync requested, run in event loop and wait for completion
        if sync:
            # call agent.run synchronously via run_sync wrapper if available
            try:
                return await asyncio.get_event_loop().run_in_executor(None, lambda: agent.run_sync(**(payload or {})))
            except Exception as e:
                logger.exception("sync run failed for agent=%s", agent_id)
                raise

        # async run: schedule and track task
        async def _runner():
            start_ts = time.time()
            try:
                res = await agent.run(**(payload or {}))
                return res
            finally:
                duration = time.time() - start_ts
                logger.info("Agent %s run completed in %.2fs", agent_id, duration)

        task = asyncio.create_task(_runner())
        # store running task
        self._running_tasks[agent_id] = task
        try:
            if timeout:
                res = await asyncio.wait_for(task, timeout)
            else:
                res = await task
            # persist audit
            await self._persist_audit(agent, payload or {}, res)
            return res
        finally:
            self._running_tasks.pop(agent_id, None)

    def run_agent_sync(self, agent_id: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> AgentResult:
        """
        Blocking wrapper for synchronous contexts / tests.
        """
        return asyncio.get_event_loop().run_until_complete(self.run_agent(agent_id=agent_id, payload=payload, sync=False, timeout=timeout))

    async def stop_agent(self, agent_id: str) -> None:
        agent = self.get_agent(agent_id)
        if not agent:
            return
        try:
            agent.cancel()
            await agent.stop()
            # cancel running task if present
            t = self._running_tasks.get(agent_id)
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        except Exception:
            logger.exception("Failed to stop agent=%s", agent_id)

    async def submit_job(self, agent_type: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None, retries: int = 0, backoff: float = 0.5) -> None:
        """
        Enqueue a job to run in background worker.
        """
        await self._queue.put({"agent_type": agent_type, "name": name, "config": config or {}, "payload": payload or {}, "retries": retries, "backoff": backoff})

    async def _persist_audit(self, agent: BaseAgent, payload: Dict[str, Any], result: Optional[AgentResult]) -> None:
        """
        Best-effort persistence of run/audit record into agent.memory if available.
        """
        try:
            record = {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "payload": payload,
                "result": (result.__dict__ if isinstance(result, AgentResult) else result),
                "ts": int(time.time()),
            }
            # memory_service exposes store_memory(agent_id, key, value, metadata)
            if hasattr(agent.memory, "store_memory"):
                await agent.memory.store_memory(agent_id=agent.id, key="audit", value=record, metadata={})
            else:
                logger.debug("No memory.store_memory available to persist audit for agent=%s", agent.id)
        except Exception:
            logger.exception("Failed to persist audit for agent=%s", agent.id)

    def available_agent_types(self) -> List[str]:
        # delegate to factory discovery helper
        try:
            return available_agent_types()
        except Exception:
            return []

    # convenience singleton accessor
def get_agent_service() -> AgentService:
    global _default_service
    if _default_service is None:
        _default_service = AgentService()
    return _default_service
