from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.lancedb_client import LanceDBClient
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.task import TaskRecord
from app.services.cache_service import CacheService


class DocumentService:
    def __init__(self) -> None:
        self.lancedb = LanceDBClient()
        self.cache_service = CacheService()

    def create_document(
        self,
        db: Session,
        *,
        filename: str,
        storage_path: str,
        content_type: str | None,
        file_size: int,
        content_hash: str,
        knowledge_base: str,
    ) -> Document:
        document = Document(
            filename=filename,
            storage_path=storage_path,
            content_type=content_type,
            file_size=file_size,
            content_hash=content_hash,
            knowledge_base=knowledge_base,
            status="uploaded",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    def list_documents(self, db: Session) -> list[Document]:
        return list(db.scalars(select(Document).order_by(Document.created_at.desc())))

    def get_document(self, db: Session, document_id: str) -> Document | None:
        return db.get(Document, document_id)

    def find_duplicate(self, db: Session, *, content_hash: str, knowledge_base: str) -> Document | None:
        stmt = select(Document).where(
            Document.content_hash == content_hash,
            Document.knowledge_base == knowledge_base,
        )
        return db.scalar(stmt)

    def delete_document(self, db: Session, document_id: str) -> bool:
        document = db.get(Document, document_id)
        if not document:
            return False
        storage_path = Path(document.storage_path)
        self.lancedb.delete_document(document_id)
        db.delete(document)
        db.commit()
        self.cache_service.clear_namespace("search")
        if storage_path.exists():
            storage_path.unlink()
        return True

    def get_dashboard_stats(self, db: Session) -> dict[str, int]:
        total_documents = db.scalar(select(func.count()).select_from(Document)) or 0
        indexed_documents = db.scalar(select(func.count()).select_from(Document).where(Document.status == "indexed")) or 0
        failed_documents = db.scalar(select(func.count()).select_from(Document).where(Document.status == "failed")) or 0
        total_tasks = db.scalar(select(func.count()).select_from(TaskRecord)) or 0
        failed_tasks = db.scalar(select(func.count()).select_from(TaskRecord).where(TaskRecord.status == "failed")) or 0
        total_chunks = db.scalar(select(func.count()).select_from(Chunk)) or 0
        return {
            "total_documents": int(total_documents),
            "indexed_documents": int(indexed_documents),
            "failed_documents": int(failed_documents),
            "total_tasks": int(total_tasks),
            "failed_tasks": int(failed_tasks),
            "total_chunks": int(total_chunks),
        }

    def update_document_status(self, db: Session, document_id: str, status: str) -> None:
        document = db.get(Document, document_id)
        if not document:
            return
        document.status = status
        document.updated_at = datetime.utcnow()
        db.add(document)
        db.commit()


class TaskService:
    def create_task(self, db: Session, task_type: str, document_id: str | None = None) -> TaskRecord:
        task = TaskRecord(task_type=task_type, document_id=document_id, status="pending")
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def get_task(self, db: Session, task_id: str) -> TaskRecord | None:
        return db.get(TaskRecord, task_id)

    def increment_retry(self, db: Session, task_id: str) -> TaskRecord | None:
        task = db.get(TaskRecord, task_id)
        if not task:
            return None
        task.retry_count += 1
        task.status = "queued"
        task.error_message = None
        task.finished_at = None
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def update_task(
        self,
        db: Session,
        task_id: str,
        *,
        status: str,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> None:
        task = db.get(TaskRecord, task_id)
        if not task:
            return
        task.status = status
        if celery_task_id is not None:
            task.celery_task_id = celery_task_id
        task.error_message = error_message
        task.finished_at = datetime.utcnow() if finished else None
        db.add(task)
        db.commit()
