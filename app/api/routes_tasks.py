from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_document_service, get_task_service
from app.db.postgres import get_db
from app.schemas.task_schema import TaskRead
from app.services.document_service import DocumentService, TaskService
from app.workers.ingestion_tasks import ingest_document

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    task_service: TaskService = Depends(get_task_service),
) -> TaskRead:
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/{task_id}/retry", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED)
def retry_task(
    task_id: str,
    db: Session = Depends(get_db),
    task_service: TaskService = Depends(get_task_service),
    document_service: DocumentService = Depends(get_document_service),
) -> TaskRead:
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if not task.document_id:
        raise HTTPException(status_code=400, detail="task is not associated with a document")

    document = document_service.get_document(db, task.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")

    retried = task_service.increment_retry(db, task_id)
    result = ingest_document.delay(document.id, document.storage_path, task_id)
    task_service.update_task(db, task_id, status="queued", celery_task_id=result.id)
    refreshed = task_service.get_task(db, task_id)
    return refreshed or retried or task
