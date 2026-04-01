from app.services.chunk_service import ChunkService


def test_chunk_text_splits_long_text() -> None:
    service = ChunkService()
    text = "token " * 400
    chunks = service.chunk_text(text, source="unit-test")
    assert len(chunks) >= 2
    assert chunks[0]["chunk_index"] == 0

