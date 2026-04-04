from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.postgres import Base
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.task import TaskRecord
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


def test_delete_document_removes_pg_rows_lancedb_rows_and_file(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    file_path = tmp_path / "notes.md"
    file_path.write_text("hello world", encoding="utf-8")

    document = Document(
        filename="notes.md",
        storage_path=str(file_path),
        content_type="text/markdown",
        file_size=11,
        content_hash="hash-1",
        knowledge_base="systems",
        status="indexed",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    db.add(
        Chunk(
            document_id=document.id,
            chunk_index=0,
            content="hello world",
            token_count=2,
            char_count=11,
            source=str(file_path),
            status="indexed",
        )
    )
    db.add(TaskRecord(document_id=document.id, task_type="ingest_and_index", status="completed"))
    db.commit()

    deleted_document_ids: list[str] = []
    cleared_namespaces: list[str] = []

    service = DocumentService()
    monkeypatch.setattr(service.lancedb, "delete_document", lambda document_id: deleted_document_ids.append(document_id))
    monkeypatch.setattr(service.cache_service, "clear_namespace", lambda namespace: cleared_namespaces.append(namespace))

    deleted = service.delete_document(db, document.id)

    assert deleted is True
    assert deleted_document_ids == [document.id]
    assert cleared_namespaces == ["search"]
    assert db.get(Document, document.id) is None
    assert db.scalar(select(Chunk).where(Chunk.document_id == document.id)) is None
    assert db.scalar(select(TaskRecord).where(TaskRecord.document_id == document.id)) is None
    assert not file_path.exists()

    db.close()
    engine.dispose()


def test_delete_document_returns_false_for_missing_document(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    service = DocumentService()

    assert service.delete_document(db, "missing-doc") is False

    db.close()
    engine.dispose()
