from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes_docs import router as docs_router
from app.api.routes_infra import router as infra_router
from app.api.routes_query import router as query_router
from app.api.routes_tasks import router as tasks_router
from app.core.config import settings
from app.core.logger import configure_logging
from app.core.metrics import metrics_response
from app.db.lancedb_client import LanceDBClient
from app.db.postgres import init_db

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name)

    @app.on_event("startup")
    def startup() -> None:
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        init_db()
        LanceDBClient().ensure_table()

        # Initialize OpenTelemetry tracing
        from app.infra.tracing import init_tracing, instrument_fastapi
        init_tracing()
        instrument_fastapi(app)

        # Initialize provider registry (triggers model warmup for Ollama)
        from app.infra.provider_registry import ProviderRegistry
        ProviderRegistry.get_instance()

    # --- Health checks ---

    @app.get("/health")
    def health() -> dict[str, str]:
        """Shallow liveness probe for K8s."""
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready() -> dict:
        """Deep readiness probe: checks DB, Redis, and model services."""
        checks: dict[str, bool] = {}

        # Database check
        try:
            from app.db.postgres import SessionLocal
            db = SessionLocal()
            db.execute(db.bind.dialect.do_ping if hasattr(db.bind.dialect, "do_ping") else __import__("sqlalchemy").text("SELECT 1"))
            db.close()
            checks["database"] = True
        except Exception:
            checks["database"] = False

        # Redis check
        try:
            from app.db.redis_client import get_redis
            r = get_redis()
            if r is not None:
                r.ping()
                checks["redis"] = True
            else:
                checks["redis"] = False
        except Exception:
            checks["redis"] = False

        # Model service checks
        try:
            from app.infra.provider_registry import ProviderRegistry
            registry = ProviderRegistry.get_instance()
            model_health = registry.health_check_all()
            checks.update(model_health)
        except Exception:
            checks["models"] = False

        all_healthy = all(checks.values())
        status_code = 200 if all_healthy else 503
        from starlette.responses import JSONResponse
        return JSONResponse(
            content={"status": "ready" if all_healthy else "not_ready", "checks": checks},
            status_code=status_code,
        )

    @app.get("/metrics")
    def metrics():
        return metrics_response()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")

    # Rate limiting middleware
    from app.infra.rate_limiter import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    app.include_router(docs_router, prefix=settings.api_prefix)
    app.include_router(tasks_router, prefix=settings.api_prefix)
    app.include_router(query_router, prefix=settings.api_prefix)
    app.include_router(infra_router, prefix=settings.api_prefix)

    return app


app = create_app()
