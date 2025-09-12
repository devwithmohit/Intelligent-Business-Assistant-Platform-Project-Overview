import asyncio
import json
import os
import logging
import time
import uuid
import threading
from typing import Any, Dict, List, Optional

logger = (
    logging.getLogger(__name__)
    if "logging" in globals()
    else __import__("logging").getLogger(__name__)
)

# storage location (can be overridden via env or core config)
_DEFAULT_DB_PATH = os.getenv(
    "MEMORY_STORE_PATH",
    os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "traditional_db", "memory.json"
    ),
)

# ensure directory exists
os.makedirs(os.path.dirname(_DEFAULT_DB_PATH), exist_ok=True)

_file_lock = threading.Lock()


def _read_store(path: str) -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(path):
        return {"records": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to read memory store, returning empty")
        return {"records": []}


def _write_store(path: str, data: Dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


async def _io_read(path: str) -> Dict[str, Any]:
    return await asyncio.to_thread(lambda: _read_store(path))


async def _io_write(path: str, data: Dict[str, Any]) -> None:
    return await asyncio.to_thread(lambda: _write_store(path, data))


# Basic in-file JSON memory with simple text-match query. Non-blocking callers via asyncio.
async def store_memory(
    agent_id: str, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Store a memory record. Returns generated record id.
    Non-atomic multi-writer safe by using a file-level lock in thread.
    """
    path = _DEFAULT_DB_PATH
    record_id = str(uuid.uuid4())
    rec = {
        "id": record_id,
        "agent_id": agent_id,
        "key": key,
        "value": value,
        "metadata": metadata or {},
        "ts": int(time.time()),
    }

    def _write():
        with _file_lock:
            data = _read_store(path)
            records = data.get("records", [])
            records.append(rec)
            data["records"] = records
            _write_store(path, data)

    await asyncio.to_thread(_write)
    return record_id


async def get_memory(
    agent_id: Optional[str] = None, key: Optional[str] = None, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Retrieve recent memory records. If agent_id provided, filter by agent_id.
    If key provided, additionally filter by key.
    Returns up to `limit` most-recent records (list of record dicts).
    """
    path = _DEFAULT_DB_PATH

    def _read_filtered():
        with _file_lock:
            data = _read_store(path)
        records = data.get("records", [])
        # filter
        out = []
        for r in reversed(records):  # newest first
            if agent_id and r.get("agent_id") != agent_id:
                continue
            if key and r.get("key") != key:
                continue
            out.append(r)
            if len(out) >= limit:
                break
        return out

    return await asyncio.to_thread(_read_filtered)


async def query_memory_by_text(
    query: str, agent_id: Optional[str] = None, top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Best-effort text search over stored values. If vector DB configured this should be replaced.
    Returns up to top_k records matching by substring frequency (simple score).
    """
    if not query:
        return []

    q = query.lower().strip().split()
    all_recs = await get_memory(agent_id=agent_id, key=None, limit=10000)
    scored: List[Dict[str, Any]] = []
    for r in all_recs:
        text = json.dumps(r.get("value", ""), ensure_ascii=False).lower()
        score = 0
        for token in q:
            if token and token in text:
                score += text.count(token)
        if score > 0:
            scored.append({"record": r, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return [s["record"] for s in scored[:top_k]]


async def clear_memory(
    agent_id: Optional[str] = None, key: Optional[str] = None
) -> int:
    """
    Remove matching memory records. Returns number of removed records.
    """
    path = _DEFAULT_DB_PATH

    def _clear():
        with _file_lock:
            data = _read_store(path)
            records = data.get("records", [])
            new_records = []
            removed = 0
            for r in records:
                if agent_id and r.get("agent_id") != agent_id:
                    new_records.append(r)
                    continue
                if key and r.get("key") != key:
                    new_records.append(r)
                    continue
                # otherwise remove
                removed += 1
            data["records"] = new_records
            _write_store(path, data)
        return removed

    return await asyncio.to_thread(_clear)


# Vector store placeholders (attempt to initialize if PINECONE_KEY exists).
_VECTOR_ENABLED = False
try:
    PINECONE_KEY = os.getenv("PINECONE_KEY")
    if PINECONE_KEY:
        import pinecone  # type: ignore

        # lazy init handled by callers if implemented; leave disabled by default to avoid hard dependency
        _VECTOR_ENABLED = False
except Exception:
    _VECTOR_ENABLED = False


async def upsert_vector(
    id: str, vector: List[float], metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Placeholder for upserting a vector to a vector DB. Raises NotImplementedError when no provider configured.
    """
    if not _VECTOR_ENABLED:
        raise NotImplementedError("Vector store not configured")
    # Implement provider-specific upsert here if enabling vector DB


async def query_vector(
    vector: List[float], top_k: int = 5, namespace: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Placeholder for vector similarity query. Raises NotImplementedError when not configured.
    """
    if not _VECTOR_ENABLED:
        raise NotImplementedError("Vector store not configured")
    return []


# Convenience singleton-like exports (module-level functions are used by agents/services)
_default_service = None


def get_memory_service():
    """
    Return module-level service placeholder for callers that expect an object.
    """
    return {
        "store_memory": store_memory,
        "get_memory": get_memory,
        "query_memory_by_text": query_memory_by_text,
        "clear_memory": clear_memory,
        "upsert_vector": upsert_vector,
        "query_vector": query_vector,
    }
