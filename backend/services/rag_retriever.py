# ...existing code...
import asyncio
import logging
import math
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import embeddings as _embeddings
from .vector_db import chroma_client as _chroma

logger = logging.getLogger(__name__)


# Type for optional rerank function: (query, hits) -> hits (sorted)
RerankFn = Callable[[str, List[Dict[str, Any]]], List[Dict[str, Any]]]


async def build_index(
    collection_name: str,
    docs: Iterable[Dict[str, Any]],
    text_key: str = "text",
    id_key: str = "id",
    metadata_key: str = "metadata",
    batch_size: int = 64,
) -> Dict[str, Any]:
    """
    Build / upsert embeddings for docs into a Chroma collection.

    docs: iterable of dicts containing at least text_key. If id_key not present a UUID is generated.
    Returns last upsert response (best-effort).
    """
    docs_list = list(docs)
    if not docs_list:
        return {"upserted": 0, "detail": "no documents"}

    client = _chroma.get_chroma_client()
    total = 0
    last_resp = {}
    for i in range(0, len(docs_list), batch_size):
        batch = docs_list[i : i + batch_size]
        texts = [str(d.get(text_key, "") or "") for d in batch]
        ids = [str(d.get(id_key) or uuid.uuid4()) for d in batch]
        metadatas = []
        for d in batch:
            meta = d.get(metadata_key, {}) or {}
            # include source id if present
            if id_key in d:
                meta.setdefault("source_id", d.get(id_key))
            metadatas.append(meta)

        # request embeddings
        try:
            emb_resp = await _embeddings.embed(texts, model=None)
            embeddings = getattr(emb_resp, "embeddings", []) or []
        except Exception as e:
            logger.exception("Embedding generation failed for batch: %s", e)
            raise

        if not embeddings or len(embeddings) != len(texts):
            raise RuntimeError("Embeddings length mismatch")

        # upsert into chroma
        try:
            last_resp = await client.upsert(
                collection_name=collection_name,
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=texts,
            )
            total += len(ids)
        except Exception:
            logger.exception("Chroma upsert failed for collection=%s", collection_name)
            raise

    return {"upserted": total, "last_resp": last_resp}


def _normalize_chroma_result(raw: Any) -> List[Dict[str, Any]]:
    """
    Normalize chroma_client.query return shapes into a list of hits:
      [{ "id", "document"|"text", "metadata", "score"/"distance" }, ...]
    """
    out: List[Dict[str, Any]] = []

    if isinstance(raw, list):
        # already list of dicts
        for item in raw:
            if not isinstance(item, dict):
                continue
            # try to handle common keys
            id_ = item.get("id") or item.get("ids") or item.get("uuid")
            doc = item.get("document") or item.get("text") or item.get("documents") or item.get("documents", None)
            meta = item.get("metadata") or item.get("metadatas") or item.get("metadata", {})
            score = item.get("distance") or item.get("score") or None
            out.append({"id": id_, "text": doc, "metadata": meta, "score": score})
        return out

    # unknown shape -> return empty
    return out


async def retrieve(
    collection_name: str,
    query: str,
    top_k: int = 5,
    rerank_fn: Optional[RerankFn] = None,
    allow_empty_query: bool = False,
) -> List[Dict[str, Any]]:
    """
    Retrieve top_k documents from collection for query.
    - computes query embedding via embeddings.embed
    - queries chroma via chroma_client.query
    - returns normalized hits list
    - optional rerank_fn can be provided to reorder hits (sync or async)
    """
    if not query and not allow_empty_query:
        return []

    client = _chroma.get_chroma_client()

    # compute embedding for query
    try:
        emb_resp = await _embeddings.embed([query], model=None)
        emb_list = getattr(emb_resp, "embeddings", []) or []
    except Exception:
        logger.exception("Failed to embed query")
        raise

    if not emb_list or not isinstance(emb_list[0], list):
        raise RuntimeError("Embedding service returned unexpected shape")

    query_emb = emb_list[0]

    # query chroma
    try:
        raw_hits = await client.query(collection_name, query_embedding=query_emb, n_results=top_k)
    except Exception:
        logger.exception("Chroma query failed for collection=%s", collection_name)
        raise

    hits = _normalize_chroma_result(raw_hits)

    # fallback scoring: convert distances to scores (smaller distance -> higher score)
    for h in hits:
        if h.get("score") is None and isinstance(h.get("metadata"), dict):
            # try to extract numeric distances from metadata if present
            pass

    # simple numeric normalization if distances present
    distances = [h.get("score") for h in hits if isinstance(h.get("score"), (int, float))]
    if distances:
        # treat as distances -> convert to score 1/(1+dist)
        for h in hits:
            d = h.get("score")
            if isinstance(d, (int, float)):
                h["score"] = 1.0 / (1.0 + max(0.0, float(d)))
    else:
        # fallback: lexical match count (cheap heuristic)
        q_tokens = [t.lower() for t in query.split() if t]
        for h in hits:
            txt = (h.get("text") or "") or ""
            cnt = sum(1 for tk in q_tokens if tk in txt.lower())
            # simple score scaled by token matches and text length
            h["score"] = (cnt + 0.0) / max(1.0, math.log(1.0 + len(txt)))

    # optional rerank hook (sync or async)
    if rerank_fn:
        try:
            if asyncio.iscoroutinefunction(rerank_fn):
                hits = await rerank_fn(query, hits)  # type: ignore
            else:
                hits = rerank_fn(query, hits)  # type: ignore
        except Exception:
            logger.exception("Rerank function raised, continuing with pre-rerank ordering")

    # stable sort by score descending
    hits.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return hits