import logging
import os
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from . import chunking as _chunking
from . import embeddings as _embeddings
from .vector_db import chroma_client as _chroma
from . import rag_retriever as _rag

logger = logging.getLogger(__name__)


class KBError(Exception):
    pass


class KBManager:
    """
    Knowledge base manager:
      - create / delete collections (Chroma)
      - add documents (chunk -> embed -> upsert)
      - list collections
      - search (RAG retrieve)
      - basic export snapshot of documents/metadata
    """

    def __init__(self, default_collection_prefix: Optional[str] = "kb") -> None:
        self.prefix = default_collection_prefix or "kb"
        self.client = _chroma.get_chroma_client()
        logger.debug("KBManager initialized prefix=%s", self.prefix)

    async def list_kbs(self) -> List[str]:
        try:
            return await self.client.list_collections()
        except Exception:
            logger.exception("list_kbs failed")
            return []

    async def create_kb(self, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a named KB (collection). Returns collection name.
        """
        col = name or f"{self.prefix}-{uuid.uuid4().hex[:8]}"
        try:
            await self.client.create_collection(col, metadata=metadata or {})
            return col
        except Exception as e:
            logger.exception("create_kb failed for %s", col)
            raise KBError(str(e)) from e

    async def delete_kb(self, name: str) -> None:
        try:
            await self.client.delete_collection(name)
        except Exception as e:
            logger.exception("delete_kb failed for %s", name)
            raise KBError(str(e)) from e

    async def add_documents(
        self,
        collection_name: str,
        docs: Iterable[Dict[str, Any]],
        chunk_opts: Optional[Dict[str, Any]] = None,
        batch_size: int = 64,
    ) -> Dict[str, Any]:
        """
        Add documents to a KB:
          - docs: iterable of dicts with at least 'text' (or configurable key)
          - chunk_opts forwarded to chunking.chunk_documents
        Returns summary dict with upserted count.
        """
        chunk_opts = chunk_opts or {"max_tokens": 512, "overlap": 64}
        # produce chunks flattened
        chunks = _chunking.chunk_documents(docs, text_key="text", metadata_key="metadata", **chunk_opts)
        if not chunks:
            return {"upserted": 0, "detail": "no chunks produced"}

        # build / upsert using rag_retriever.build_index which handles embeddings/upsert
        try:
            resp = await _rag.build_index(collection_name=collection_name, docs=chunks, text_key="text", id_key="id", metadata_key="metadata", batch_size=batch_size)
            return resp
        except Exception as e:
            logger.exception("add_documents failed for collection=%s", collection_name)
            raise KBError(str(e)) from e

    async def remove_documents(self, collection_name: str, ids: Iterable[str]) -> None:
        """
        Remove documents by id from collection (Chroma delete by ids).
        """
        try:
            # direct chroma client usage (blocking wrapped inside chroma_client)
            client = self.client
            # chroma client implementation may expose collection delete(ids=[])
            def _del():
                coll = client._client.get_collection(collection_name)
                # try delete method variants
                if hasattr(coll, "delete"):
                    try:
                        coll.delete(ids=list(ids))
                        return True
                    except Exception:
                        pass
                # fallback: delete by where not supported here
                raise KBError("delete by ids not supported by chroma client version")
            await client._run_blocking(_del)
        except KBError:
            raise
        except Exception as e:
            logger.exception("remove_documents failed for %s", collection_name)
            raise KBError(str(e)) from e

    async def get_document(self, collection_name: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single document by id from chroma collection (best-effort).
        """
        try:
            hits = await self.client.query(collection_name=collection_name, query_embedding=[0.0], n_results=1, where={"id": doc_id})
            # normalize: try to find exact id match
            for h in hits:
                if h.get("id") == doc_id or (h.get("metadata") or {}).get("source_id") == doc_id:
                    return h
            return None
        except Exception:
            logger.debug("get_document best-effort fallback via list query failed for %s", doc_id)
            return None

    async def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        rerank_fn: Optional[_rag.RerankFn] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve top-k relevant chunks for query using embeddings + chroma.
        """
        try:
            return await _rag.retrieve(collection_name=collection_name, query=query, top_k=top_k, rerank_fn=rerank_fn)
        except Exception as e:
            logger.exception("search failed for collection=%s query=%s", collection_name, query)
            raise KBError(str(e)) from e

    async def snapshot(self, collection_name: str, out_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Export collection documents/metadatas into a local jsonl snapshot under out_dir.
        This is a best-effort exporter that queries all documents (may be slow for large collections).
        """
        out_dir = out_dir or os.path.join(os.getcwd(), "data", "vector_db_snapshots")
        os.makedirs(out_dir, exist_ok=True)
        ts = int(time.time())
        fname = os.path.join(out_dir, f"{collection_name}-{ts}.jsonl")
        try:
            # naive approach: query with empty embedding but chroma requires embeddings; list collection then fetch docs
            # try to access underlying chroma collection directly (best-effort)
            def _collect():
                coll = self.client._client.get_collection(collection_name)
                # some chroma versions expose get with no args returning documents/metadatas/ids
                try:
                    return coll.get(include=["ids", "documents", "metadatas"])
                except Exception:
                    # fall back to list + query per id (too slow) -> return empty
                    return {}
            res = await self.client._run_blocking(_collect)
            ids = (res.get("ids") or []) if isinstance(res, dict) else []
            docs = (res.get("documents") or []) if isinstance(res, dict) else []
            metas = (res.get("metadatas") or []) if isinstance(res, dict) else []
            # write jsonl
            import json
            with open(fname, "w", encoding="utf-8") as f:
                for i, _id in enumerate(ids):
                    item = {"id": _id, "text": docs[i] if i < len(docs) else None, "metadata": metas[i] if i < len(metas) else {}}
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            return {"snapshot": fname, "count": len(ids)}
        except Exception as e:
            logger.exception("snapshot failed for collection=%s", collection_name)
            raise KBError(str(e)) from e


# module-level singleton
_default_kb: Optional[KBManager] = None


def get_kb_manager() -> KBManager:
    global _default_kb
    if _default_kb is None:
        _default_kb = KBManager()
    return _default_kb


# convenience module-level wrappers
async def list_kbs() -> List[str]:
    return await get_kb_manager().list_kbs()


async def create_kb(name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    return await get_kb_manager().create_kb(name=name, metadata=metadata)


async def delete_kb(name: str) -> None:
    return await get_kb_manager().delete_kb(name)


async def add_documents(collection_name: str, docs: Iterable[Dict[str, Any]], chunk_opts: Optional[Dict[str, Any]] = None, batch_size: int = 64) -> Dict[str, Any]:
    return await get_kb_manager().add_documents(collection_name=collection_name, docs=docs, chunk_opts=chunk_opts, batch_size=batch_size)


async def search(collection_name: str, query: str, top_k: int = 5, rerank_fn: Optional[_rag.RerankFn] = None) -> List[Dict[str, Any]]:
    return await get_kb_manager().search(collection_name=collection_name, query=query, top_k=top_k, rerank_fn=rerank_fn)


async def snapshot(collection_name: str, out_dir: Optional[str] = None) -> Dict[str, Any]:
    return await get_kb_manager().snapshot(collection_name=collection_name, out_dir=out_dir)
