from app.services.embedding_service import EmbeddingService


def test_embedding_is_deterministic() -> None:
    service = EmbeddingService()
    vector_1 = service.embed_text("distributed retrieval pipeline")
    vector_2 = service.embed_text("distributed retrieval pipeline")
    assert vector_1 == vector_2
    assert len(vector_1) == len(vector_2)

