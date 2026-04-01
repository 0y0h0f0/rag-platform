from app.services.rerank_service import RerankService


def test_rerank_prefers_overlap() -> None:
    service = RerankService()
    hits = [
        {"text": "database systems and storage", "score": 0.4},
        {"text": "retrieval pipeline storage indexing", "score": 0.4},
    ]
    reranked = service.rerank("storage indexing", hits)
    assert reranked[0]["text"] == "retrieval pipeline storage indexing"

