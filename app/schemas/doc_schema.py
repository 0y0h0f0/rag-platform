from datetime import datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    id: str
    filename: str
    content_type: str | None
    file_size: int
    knowledge_base: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    document_id: str
    task_id: str
    status: str
    deduplicated: bool = False


class DocumentDetail(BaseModel):
    id: str
    filename: str
    content_type: str | None
    file_size: int
    content_hash: str
    knowledge_base: str
    storage_path: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DashboardStats(BaseModel):
    total_documents: int
    indexed_documents: int
    failed_documents: int
    total_tasks: int
    failed_tasks: int
    total_chunks: int
