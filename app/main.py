from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes_docs import router as docs_router
from app.api.routes_query import router as query_router
from app.api.routes_tasks import router as tasks_router
from app.core.config import settings
from app.core.logger import configure_logging
from app.core.metrics import metrics_response
from app.db.lancedb_client import LanceDBClient
from app.db.postgres import init_db


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name)

    @app.on_event("startup")
    def startup() -> None:
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        init_db()
        LanceDBClient().ensure_table()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        return metrics_response()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")

    app.include_router(docs_router, prefix=settings.api_prefix)
    app.include_router(tasks_router, prefix=settings.api_prefix)
    app.include_router(query_router, prefix=settings.api_prefix)

    return app


app = create_app()
