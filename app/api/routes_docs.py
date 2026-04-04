from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_document_service, get_task_service
from app.core.metrics import DEDUPLICATED_UPLOADS, DOCUMENT_UPLOADS
from app.db.postgres import get_db
from app.schemas.doc_schema import DashboardStats, DocumentDetail, DocumentRead, UploadResponse
from app.services.document_service import DocumentService, TaskService
from app.workers.ingestion_tasks import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_base: str = Form(default="default"),
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
    task_service: TaskService = Depends(get_task_service),
) -> UploadResponse:
    suffix = Path(file.filename or "upload.txt").suffix
    if suffix.lower() not in {".txt", ".md", ".pdf", ".rs", ".py", ".json",".cpp",".h",".c"}:
        raise HTTPException(status_code=400, detail="unsupported file type")

    storage_name = f"{uuid.uuid4().hex}{suffix}"
    upload_path = Path("./data/uploads")
    upload_path.mkdir(parents=True, exist_ok=True)
    file_path = upload_path / storage_name
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()

    duplicate = document_service.find_duplicate(db, content_hash=content_hash, knowledge_base=knowledge_base)
    if duplicate:
        existing_task = task_service.create_task(db, task_type="ingest_and_index", document_id=duplicate.id)
        task_service.update_task(db, existing_task.id, status="completed", finished=True)
        DEDUPLICATED_UPLOADS.inc()
        return UploadResponse(
            document_id=duplicate.id,
            task_id=existing_task.id,
            status="deduplicated",
            deduplicated=True,
        )

    file_path.write_bytes(content)

    document = document_service.create_document(
        db,
        filename=file.filename or storage_name,
        storage_path=str(file_path),
        content_type=file.content_type,
        file_size=len(content),
        content_hash=content_hash,
        knowledge_base=knowledge_base,
    )
    task = task_service.create_task(db, task_type="ingest_and_index", document_id=document.id)

    result = ingest_document.delay(document.id, str(file_path), task.id)
    task_service.update_task(db, task.id, status="queued", celery_task_id=result.id)
    DOCUMENT_UPLOADS.inc()

    return UploadResponse(document_id=document.id, task_id=task.id, status="queued")


@router.get("", response_model=list[DocumentRead])
def list_documents(
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
) -> list[DocumentRead]:
    return document_service.list_documents(db)


@router.get("/dashboard/summary", response_model=DashboardStats)
def dashboard_summary(
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
) -> DashboardStats:
    return DashboardStats(**document_service.get_dashboard_stats(db))


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentDetail:
    document = document_service.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
) -> Response:
    deleted = document_service.delete_document(db, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
