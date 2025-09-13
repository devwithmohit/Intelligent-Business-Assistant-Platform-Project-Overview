# ...existing code...
import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class StateManagerError(Exception):
    pass


@dataclass
class WorkflowState:
    id: str
    workflow_name: str
    created_at: float
    updated_at: float
    context: Dict[str, Any]
    metadata: Dict[str, Any]


StorageSaveHook = Callable[[str, Dict[str, Any]], None]
StorageLoadHook = Callable[[str], Optional[Dict[str, Any]]]


class StateManager:
    """
    Simple workflow state manager.
    - In-memory default storage with optional Redis persistence if available.
    - Per-instance asyncio.Lock to guard concurrent access.
    - Supports pluggable save/load hooks for durable persistence (e.g. DB, S3).
    """

    def __init__(self, persist_dir: Optional[str] = None, save_hook: Optional[StorageSaveHook] = None, load_hook: Optional[StorageLoadHook] = None):
        self._states: Dict[str, WorkflowState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._save_hook = save_hook
        self._load_hook = load_hook
        # optional simple file-based persistence directory
        self.persist_dir = persist_dir or os.getenv("WORKFLOW_STATE_DIR") or "./data/workflow_states"
        os.makedirs(self.persist_dir, exist_ok=True)
        # try to use redis.asyncio if available for optional backing store
        try:
            import redis.asyncio as aioredis  # type: ignore
            self._redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            self._use_redis = True
            logger.debug("StateManager: redis backing enabled")
        except Exception:
            self._redis = None
            self._use_redis = False
            logger.debug("StateManager: redis not available, using memory + file persistence")

    async def _get_lock(self, instance_id: str) -> asyncio.Lock:
        if instance_id not in self._locks:
            self._locks[instance_id] = asyncio.Lock()
        return self._locks[instance_id]

    def _serialize_state(self, state: WorkflowState) -> str:
        return json.dumps(asdict(state), default=str)

    def _deserialize_state(self, payload: str) -> WorkflowState:
        data = json.loads(payload)
        return WorkflowState(**data)

    async def create_instance(self, workflow_name: str, initial_context: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> WorkflowState:
        instance_id = f"{workflow_name}-{uuid.uuid4().hex[:8]}"
        now = time.time()
        state = WorkflowState(
            id=instance_id,
            workflow_name=workflow_name,
            created_at=now,
            updated_at=now,
            context=initial_context or {},
            metadata=metadata or {},
        )
        self._states[instance_id] = state
        # persist if possible
        await self._maybe_persist(state)
        logger.debug("Created workflow instance %s", instance_id)
        return state

    async def get_instance(self, instance_id: str) -> Optional[WorkflowState]:
        # try in-memory first
        state = self._states.get(instance_id)
        if state:
            return state
        # try load hook
        if self._load_hook:
            raw = self._load_hook(instance_id)
            if raw:
                st = WorkflowState(**raw)
                self._states[instance_id] = st
                return st
        # try file or redis
        # file
        path = os.path.join(self.persist_dir, f"{instance_id}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = f.read()
                state = self._deserialize_state(payload)
                self._states[instance_id] = state
                return state
            except Exception:
                logger.exception("Failed to load state from file %s", path)
        # redis
        if self._use_redis and self._redis:
            try:
                payload = await self._redis.get(instance_id)
                if payload:
                    state = self._deserialize_state(payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload))
                    self._states[instance_id] = state
                    return state
            except Exception:
                logger.debug("Redis get failed for %s", instance_id)
        return None

    async def update_instance(self, instance_id: str, patch: Dict[str, Any], merge: bool = True) -> WorkflowState:
        lock = await self._get_lock(instance_id)
        async with lock:
            state = await self.get_instance(instance_id)
            if not state:
                raise StateManagerError(f"instance not found: {instance_id}")
            if merge:
                # shallow merge context
                ctx = dict(state.context or {})
                ctx.update(patch.get("context", {}) or {})
                state.context = ctx
                # update metadata if provided
                if "metadata" in patch:
                    meta = dict(state.metadata or {})
                    meta.update(patch.get("metadata") or {})
                    state.metadata = meta
            else:
                # replace
                if "context" in patch:
                    state.context = patch.get("context") or {}
                if "metadata" in patch:
                    state.metadata = patch.get("metadata") or {}
            state.updated_at = time.time()
            self._states[instance_id] = state
            await self._maybe_persist(state)
            logger.debug("Updated instance %s", instance_id)
            return state

    async def set_key(self, instance_id: str, key: str, value: Any) -> WorkflowState:
        return await self.update_instance(instance_id, {"context": {key: value}}, merge=True)

    async def get_key(self, instance_id: str, key: str, default: Any = None) -> Any:
        state = await self.get_instance(instance_id)
        if not state:
            return default
        return state.context.get(key, default)

    async def delete_instance(self, instance_id: str) -> None:
        lock = await self._get_lock(instance_id)
        async with lock:
            if instance_id in self._states:
                del self._states[instance_id]
            # delete persisted files if present
            path = os.path.join(self.persist_dir, f"{instance_id}.json")
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                logger.debug("Failed to remove state file %s", path)
            if self._use_redis and self._redis:
                try:
                    await self._redis.delete(instance_id)
                except Exception:
                    logger.debug("Failed to delete redis key %s", instance_id)
            logger.debug("Deleted instance %s", instance_id)

    async def list_instances(self) -> Dict[str, Dict[str, Any]]:
        return {k: {"workflow_name": v.workflow_name, "created_at": v.created_at, "updated_at": v.updated_at} for k, v in self._states.items()}

    async def snapshot_instance(self, instance_id: str, out_path: Optional[str] = None) -> str:
        state = await self.get_instance(instance_id)
        if not state:
            raise StateManagerError("instance not found")
        out_path = out_path or os.path.join(self.persist_dir, f"{instance_id}.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(self._serialize_state(state))
            logger.info("Snapshot saved to %s", out_path)
            return out_path
        except Exception as e:
            logger.exception("Failed to write snapshot for %s: %s", instance_id, e)
            raise StateManagerError(str(e)) from e

    async def _maybe_persist(self, state: WorkflowState) -> None:
        """
        Try to persist state using hooks, redis, or file system. Failures are logged but not raised.
        """
        payload = asdict(state)
        # custom save hook (sync)
        if self._save_hook:
            try:
                self._save_hook(state.id, payload)
            except Exception:
                logger.exception("save_hook failed for %s", state.id)
        # redis
        if self._use_redis and self._redis:
            try:
                await self._redis.set(state.id, self._serialize_state(state))
            except Exception:
                logger.debug("Redis set failed for %s", state.id)
        # file fallback
        try:
            path = os.path.join(self.persist_dir, f"{state.id}.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._serialize_state(state))
        except Exception:
            logger.debug("File persist failed for %s", state.id)

    # convenience synchronous wrappers (for sync code)
    def create_instance_sync(self, workflow_name: str, initial_context: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> WorkflowState:
        return asyncio.get_event_loop().run_until_complete(self.create_instance(workflow_name, initial_context, metadata))

    # simple health check
    async def health(self) -> Dict[str, Any]:
        return {"instances": len(self._states), "redis": bool(self._use_redis)}

# module-level singleton
_default_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    global _default_state_manager
    if _default_state_manager is None:
        _default_state_manager = StateManager()
    return _default_state_manager
# ...existing code...