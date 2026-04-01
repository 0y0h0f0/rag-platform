from datetime import datetime

from pydantic import BaseModel


class TaskRead(BaseModel):
    id: str
    document_id: str | None
    task_type: str
    status: str
    celery_task_id: str | None
    error_message: str | None
    retry_count: int
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}
