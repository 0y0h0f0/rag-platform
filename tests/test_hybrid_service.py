from app.services.hybrid_service import HybridSearchService


def test_hybrid_fusion_merges_rankings() -> None:
    service = HybridSearchService()
    vector_hits = [
        {"chunk_id": "a", "text": "distributed systems scheduling", "score": 0.7},
        {"chunk_id": "b", "text": "query scheduling indexing retrieval", "score": 0.65},
    ]
    lexical_hits = [
        {"chunk_id": "b", "text": "query scheduling indexing retrieval", "score": 2.1},
        {"chunk_id": "c", "text": "message queue throughput", "score": 1.3},
    ]
    fused = service.fuse(vector_hits, lexical_hits, top_k=3)
    assert fused[0]["chunk_id"] == "b"
    assert {hit["chunk_id"] for hit in fused} == {"a", "b", "c"}
