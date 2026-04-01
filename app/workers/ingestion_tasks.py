from __future__ import annotations

from celery.utils.log import get_task_logger

from app.core.metrics import INGESTION_TASKS
from app.db.postgres import SessionLocal
from app.services.cache_service import CacheService
from app.services.chunk_service import ChunkService
from app.services.document_service import DocumentService, TaskService
from app.workers.celery_app import celery_app
from app.workers.embedding_tasks import embed_document

logger = get_task_logger(__name__)


@celery_app.task(name="app.workers.ingestion_tasks.ingest_document")
def ingest_document(document_id: str, file_path: str, task_id: str) -> dict:
    db = SessionLocal()
    document_service = DocumentService()
    task_service = TaskService()
    chunk_service = ChunkService()
    cache_service = CacheService()

    try:
        document_service.update_document_status(db, document_id, "processing")
        task_service.update_task(db, task_id, status="processing")
        raw_text = chunk_service.extract_text(file_path)
        chunks = chunk_service.chunk_text(raw_text, source=file_path)
        saved_chunks = chunk_service.replace_document_chunks(db, document_id, chunks)
        cache_service.clear_namespace("search")
        embed_document.delay(document_id, task_id)
        INGESTION_TASKS.labels(status="success").inc()
        logger.info("ingested document %s with %s chunks", document_id, len(saved_chunks))
        return {"document_id": document_id, "chunks": len(saved_chunks)}
    except Exception as exc:  # noqa: BLE001
        document_service.update_document_status(db, document_id, "failed")
        task_service.update_task(db, task_id, status="failed", error_message=str(exc), finished=True)
        INGESTION_TASKS.labels(status="failed").inc()
        raise
    finally:
        db.close()
