from __future__ import annotations

from celery.utils.log import get_task_logger

from app.db.postgres import SessionLocal
from app.services.cache_service import CacheService
from app.services.chunk_service import ChunkService
from app.services.document_service import DocumentService, TaskService
from app.services.retrieval_service import RetrievalService
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="app.workers.embedding_tasks.embed_document")
def embed_document(document_id: str, task_id: str) -> dict:
    db = SessionLocal()
    chunk_service = ChunkService()
    retrieval_service = RetrievalService()
    document_service = DocumentService()
    task_service = TaskService()
    cache_service = CacheService()

    try:
        chunks = chunk_service.get_document_chunks(db, document_id)
        indexed = retrieval_service.index_chunks(db, chunks)
        cache_service.clear_namespace("search")
        document_service.update_document_status(db, document_id, "indexed")
        task_service.update_task(db, task_id, status="completed", finished=True)
        logger.info("indexed %s chunks for document %s", indexed, document_id)
        return {"document_id": document_id, "indexed": indexed}
    except Exception as exc:  # noqa: BLE001
        document_service.update_document_status(db, document_id, "failed")
        task_service.update_task(db, task_id, status="failed", error_message=str(exc), finished=True)
        raise
    finally:
        db.close()
