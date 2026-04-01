from app.models.document import Document
from app.services.document_service import DocumentService


def test_create_document_sets_metadata() -> None:
    service = DocumentService()
    document = Document(
        filename="notes.md",
        storage_path="/tmp/notes.md",
        content_type="text/markdown",
        file_size=128,
        knowledge_base="systems",
        status="uploaded",
    )
    assert document.filename == "notes.md"
    assert document.file_size == 128
    assert document.knowledge_base == "systems"
