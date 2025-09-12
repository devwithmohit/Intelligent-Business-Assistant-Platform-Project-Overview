from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class KBDoc(BaseModel):
    """
    Document input for KB ingestion.
    """
    id: Optional[str] = Field(None, example="doc-123")
    text: str = Field(..., example="The full document text or passage to index.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class KBChunk(BaseModel):
    """
    Individual chunk produced by the chunking pipeline.
    """
    id: str = Field(..., example="chunk-uuid-1")
    text: str = Field(..., example="Chunk text")
    tokens: Optional[int] = Field(None, example=256)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class KBCreateRequest(BaseModel):
    """
    Request to create a new knowledge base (collection).
    """
    name: Optional[str] = Field(None, description="Optional collection name. If omitted a generated name is used.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class KBAddDocsRequest(BaseModel):
    """
    Request to add documents to a KB. Documents will be chunked/embedded before upsert.
    """
    collection_name: str = Field(..., example="kb-sales-01")
    docs: List[KBDoc] = Field(..., description="List of documents to add")
    chunk_opts: Optional[Dict[str, Any]] = Field(default_factory=lambda: {"max_tokens": 512, "overlap": 64}, description="Options forwarded to chunking (max_tokens, overlap, min_tokens)")


class KBSearchRequest(BaseModel):
    """
    Search/retrieve request against a KB.
    """
    collection_name: str = Field(..., example="kb-sales-01")
    query: str = Field(..., example="prospect outreach best practices")
    top_k: int = Field(5, description="Number of top results to return")
    rerank: Optional[bool] = Field(False, description="If true, allow optional reranking (LLM or custom) on results")


class KBSearchResultItem(BaseModel):
    """
    Single retrieval result item.
    """
    id: Optional[str] = Field(None, example="chunk-uuid-1")
    text: Optional[str] = Field(None, example="Relevant chunk text")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    score: Optional[float] = Field(None, example=0.87)


class KBSearchResponse(BaseModel):
    """
    Search response containing ordered results.
    """
    results: List[KBSearchResultItem] = Field(default_factory=list)
    count: int = Field(0)


class KBSnapshotResponse(BaseModel):
    """
    Response when exporting a snapshot of a collection.
    """
    snapshot_path: str = Field(..., example="data/vector_db_snapshots/kb-sales-01-1612345678.jsonl")
    count: int = Field(..., example=120)
    generated_at: Optional[int] = Field(None, description="Unix timestamp when snapshot was created")