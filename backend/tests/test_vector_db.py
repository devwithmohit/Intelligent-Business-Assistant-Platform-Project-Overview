import asyncio
import pytest
from backend.services import rag_retriever as rag


class _DummyClient:
    def __init__(self, upsert_resp=None, query_resp=None):
        self._upsert_resp = upsert_resp or {"ok": True}
        self._query_resp = query_resp or []
        self.upsert_calls = []
        self.query_calls = []

    async def upsert(
        self, collection_name, ids, embeddings, metadatas=None, documents=None
    ):
        self.upsert_calls.append(
            dict(
                collection_name=collection_name,
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            )
        )
        return self._upsert_resp

    async def query(self, collection_name, query_embedding=None, n_results=5):
        self.query_calls.append(
            dict(
                collection_name=collection_name,
                query_embedding=query_embedding,
                n_results=n_results,
            )
        )
        return self._query_resp


@pytest.mark.asyncio
async def test_build_index_empty_docs_returns_zero():
    resp = await rag.build_index("col", [])
    assert resp["upserted"] == 0
    assert "detail" in resp


@pytest.mark.asyncio
async def test_build_index_upserts_embeddings(monkeypatch):
    # prepare dummy embed response and chroma client
    async def fake_embed(texts, model=None):
        # return object with .embeddings attribute
        class R:
            pass

        r = R()
        r.embeddings = [[float(i)] * 3 for i, _ in enumerate(texts, 1)]
        return r

    client = _DummyClient(upsert_resp={"upserted": "batch"})

    monkeypatch.setattr(rag, "_embeddings", rag._embeddings)
    monkeypatch.setattr(rag._embeddings, "embed", fake_embed)
    monkeypatch.setattr(rag._chroma, "get_chroma_client", lambda: client)

    docs = [{"id": "a", "text": "hello"}, {"id": "b", "text": "world"}]
    resp = await rag.build_index("mycol", docs, batch_size=2)
    assert resp["upserted"] == 2
    assert "last_resp" in resp or resp.get("last_resp", None) is not None
    # ensure upsert was called on client
    assert client.upsert_calls
    call = client.upsert_calls[0]
    assert call["collection_name"] == "mycol"
    assert len(call["ids"]) == 2
    assert len(call["embeddings"]) == 2


@pytest.mark.asyncio
async def test_build_index_propagates_embedding_errors(monkeypatch):
    async def bad_embed(texts, model=None):
        raise RuntimeError("embed failed")

    monkeypatch.setattr(rag._embeddings, "embed", bad_embed)
    with pytest.raises(RuntimeError):
        await rag.build_index("col", [{"text": "x"}])


@pytest.mark.asyncio
async def test_retrieve_empty_query_disallowed(monkeypatch):
    # should return empty list without calling embed/query when query empty and not allowed
    called = {"embed": False, "query": False}

    async def fake_embed(texts, model=None):
        called["embed"] = True

        class R:
            pass

        r = R()
        r.embeddings = [[0.0]] * len(texts)
        return r

    client = _DummyClient(query_resp=[])
    monkeypatch.setattr(rag._embeddings, "embed", fake_embed)
    monkeypatch.setattr(rag._chroma, "get_chroma_client", lambda: client)

    hits = await rag.retrieve("col", "", top_k=3, allow_empty_query=False)
    assert hits == []
    assert not called["embed"]
    assert client.query_calls == []


@pytest.mark.asyncio
async def test_retrieve_allow_empty_query_calls_embed_and_query(monkeypatch):
    called = {"embed": 0, "query": 0}

    async def fake_embed(texts, model=None):
        called["embed"] += 1

        class R:
            pass

        r = R()
        r.embeddings = [[0.1, 0.2, 0.3]]
        return r

    client = _DummyClient(query_resp=[])

    async def fake_query(collection_name, query_embedding=None, n_results=5):
        called["query"] += 1
        return []

    client.query = fake_query  # override method
    monkeypatch.setattr(rag._embeddings, "embed", fake_embed)
    monkeypatch.setattr(rag._chroma, "get_chroma_client", lambda: client)

    hits = await rag.retrieve("col", "", top_k=2, allow_empty_query=True)
    assert isinstance(hits, list)
    assert called["embed"] == 1
    assert called["query"] == 1


@pytest.mark.asyncio
async def test_retrieve_converts_distances_to_scores_and_sorts(monkeypatch):
    async def fake_embed(texts, model=None):
        class R:
            pass

        r = R()
        r.embeddings = [[0.0]]
        return r

    # chroma returns list of dicts with 'distance' numeric values
    raw_hits = [
        {"id": "low_dist", "text": "low distance doc", "metadata": {}, "distance": 0.1},
        {"id": "high_dist", "text": "higher distance", "metadata": {}, "distance": 2.0},
    ]
    client = _DummyClient(query_resp=raw_hits)
    monkeypatch.setattr(rag._embeddings, "embed", fake_embed)
    monkeypatch.setattr(rag._chroma, "get_chroma_client", lambda: client)

    hits = await rag.retrieve("col", "query text", top_k=2)
    assert len(hits) == 2
    # scores should be computed as 1/(1+distance) => low_dist score > high_dist score
    scores = {h["id"]: h["score"] for h in hits}
    assert scores["low_dist"] > scores["high_dist"]


@pytest.mark.asyncio
async def test_retrieve_lexical_scoring_when_no_numeric_distances(monkeypatch):
    async def fake_embed(texts, model=None):
        class R:
            pass

        r = R()
        r.embeddings = [[0.0]]
        return r

    raw_hits = [
        {"id": "match", "text": "the quick brown fox", "metadata": {}},
        {"id": "no_match", "text": "unrelated content here", "metadata": {}},
    ]
    client = _DummyClient(query_resp=raw_hits)
    monkeypatch.setattr(rag._embeddings, "embed", fake_embed)
    monkeypatch.setattr(rag._chroma, "get_chroma_client", lambda: client)

    hits = await rag.retrieve("col", "quick fox", top_k=2)
    assert len(hits) == 2
    # match should have higher score due to token overlap
    assert hits[0]["id"] == "match"


@pytest.mark.asyncio
async def test_retrieve_rerank_sync_and_async(monkeypatch):
    async def fake_embed(texts, model=None):
        class R:
            pass

        r = R()
        r.embeddings = [[0.0]]
        return r

    raw_hits = [
        {"id": "a", "text": "a text", "metadata": {}, "distance": 0.5},
        {"id": "b", "text": "b text", "metadata": {}, "distance": 0.6},
    ]
    client = _DummyClient(query_resp=raw_hits)
    monkeypatch.setattr(rag._embeddings, "embed", fake_embed)
    monkeypatch.setattr(rag._chroma, "get_chroma_client", lambda: client)

    # sync rerank function: reverse order
    def sync_rerank(query, hits):
        return list(reversed(hits))

    hits_sync = await rag.retrieve("col", "q", top_k=2, rerank_fn=sync_rerank)
    assert hits_sync[0]["id"] == "b"  # reversed

    # async rerank
    async def async_rerank(query, hits):
        await asyncio.sleep(0)  # ensure coroutine
        return sorted(hits, key=lambda h: h["id"])  # sort by id ascending

    hits_async = await rag.retrieve("col", "q", top_k=2, rerank_fn=async_rerank)
    assert hits_async[0]["id"] == "a"
