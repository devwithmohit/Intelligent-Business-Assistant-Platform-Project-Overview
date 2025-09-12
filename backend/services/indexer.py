import logging
import os
from typing import Any, Dict, Iterable, List, Optional

from . import chunking as _chunking
from . import embeddings as _embeddings
from .vector_db import chroma_client as _chroma

logger = logging.getLogger(__name__)


class IndexerError(Exception):
    pass


class Indexer:
    """
    High-level orchestration for indexing documents:
      - chunk documents
      - embed chunks (batched)
      - upsert into Chroma collections
    """

    def __init__(self) -> None:
        # default chunking options
        self.default_chunk_opts = {"max_tokens": 512, "overlap": 64, "min_tokens": 8}

    async def index_documents(
        self,
        collection_name: str,
        docs: Iterable[Dict[str, Any]],
        chunk_opts: Optional[Dict[str, Any]] = None,
        embed_batch_size: int = 64,
    ) -> Dict[str, Any]:
        """
        Chunk, embed and upsert provided documents into the named collection.
        Returns summary: { indexed: int, last_resp: dict }
        """
        chunk_opts = {**self.default_chunk_opts, **(chunk_opts or {})}
        # produce flattened chunks
        chunks = _chunking.chunk_documents(
            docs, text_key="text", metadata_key="metadata", **chunk_opts
        )
        if not chunks:
            return {"indexed": 0, "detail": "no chunks produced"}

        client = _chroma.get_chroma_client()
        total = 0
        last_resp: Dict[str, Any] = {}
        try:
            # ensure collection exists
            await client.get_or_create_collection(collection_name, metadata={})
        except Exception:
            logger.debug("Failed to ensure collection exists; continuing")

        # upsert in batches
        for i in range(0, len(chunks), embed_batch_size):
            batch = chunks[i : i + embed_batch_size]
            texts = [str(c.get("text") or "") for c in batch]
            ids = [str(c.get("id") or "") for c in batch]
            metadatas = [c.get("metadata") or {} for c in batch]

            # generate embeddings
            try:
                emb_resp = await _embeddings.embed(texts, model=None)
                embeddings = getattr(emb_resp, "embeddings", []) or []
            except Exception as e:
                logger.exception(
                    "Embedding generation failed for batch starting at %d: %s", i, e
                )
                raise IndexerError(str(e)) from e

            if not embeddings or len(embeddings) != len(texts):
                raise IndexerError("embeddings length mismatch")

            # upsert to chroma
            try:
                resp = await client.upsert(
                    collection_name=collection_name,
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=texts,
                )
                last_resp = resp
                total += len(ids)
            except Exception as e:
                logger.exception(
                    "Chroma upsert failed for collection=%s: %s", collection_name, e
                )
                raise IndexerError(str(e)) from e

        # persist if available
        try:
            await client.persist()
        except Exception:
            logger.debug("Chroma persist not available or failed")

        return {"indexed": total, "last_resp": last_resp}

    async def delete_collection(self, collection_name: str) -> None:
        client = _chroma.get_chroma_client()
        try:
            await client.delete_collection(collection_name)
        except Exception as e:
            logger.exception("delete_collection failed for %s: %s", collection_name, e)
            raise IndexerError(str(e)) from e

    async def list_collections(self) -> List[str]:
        client = _chroma.get_chroma_client()
        try:
            return await client.list_collections()
        except Exception:
            logger.exception("list_collections failed")
            return []

    async def reindex(
        self,
        collection_name: str,
        docs: Iterable[Dict[str, Any]],
        chunk_opts: Optional[Dict[str, Any]] = None,
        embed_batch_size: int = 64,
        recreate: bool = False,
    ) -> Dict[str, Any]:
        """
        Optionally recreate collection and index provided docs.
        """
        if recreate:
            try:
                await self.delete_collection(collection_name)
            except Exception:
                # ignore deletion errors when recreating
                pass
        return await self.index_documents(
            collection_name=collection_name,
            docs=docs,
            chunk_opts=chunk_opts,
            embed_batch_size=embed_batch_size,
        )


# module-level singleton
_default_indexer: Optional[Indexer] = None


def get_indexer() -> Indexer:
    global _default_indexer
    if _default_indexer is None:
        _default_indexer = Indexer()
    return _default_indexer


# convenience wrappers
async def index_documents(
    collection_name: str,
    docs: Iterable[Dict[str, Any]],
    chunk_opts: Optional[Dict[str, Any]] = None,
    embed_batch_size: int = 64,
) -> Dict[str, Any]:
    return await get_indexer().index_documents(
        collection_name=collection_name,
        docs=docs,
        chunk_opts=chunk_opts,
        embed_batch_size=embed_batch_size,
    )


async def reindex(
    collection_name: str,
    docs: Iterable[Dict[str, Any]],
    chunk_opts: Optional[Dict[str, Any]] = None,
    embed_batch_size: int = 64,
    recreate: bool = False,
) -> Dict[str, Any]:
    return await get_indexer().reindex(
        collection_name=collection_name,
        docs=docs,
        chunk_opts=chunk_opts,
        embed_batch_size=embed_batch_size,
        recreate=recreate,
    )


async def list_collections() -> List[str]:
    return await get_indexer().list_collections()


async def delete_collection(collection_name: str) -> None:
    return await get_indexer().delete_collection(collection_name)
