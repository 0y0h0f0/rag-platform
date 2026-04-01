from types import SimpleNamespace

from app.services.bm25_service import BM25Service


def test_bm25_prefers_relevant_document() -> None:
    service = BM25Service()
    chunks = [
        SimpleNamespace(
            id="1",
            document_id="doc-1",
            content="hybrid retrieval combines semantic search with lexical ranking",
            source="doc-1",
            chunk_index=0,
        ),
        SimpleNamespace(
            id="2",
            document_id="doc-2",
            content="distributed systems need observability and fault tolerance",
            source="doc-2",
            chunk_index=0,
        ),
    ]
    hits = service.score("lexical ranking", chunks, top_k=2)
    assert hits[0]["document_id"] == "doc-1"
