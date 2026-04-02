# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAG (Retrieval-Augmented Generation) platform built with FastAPI. Supports document upload, chunking, embedding, multi-mode retrieval (vector/lexical/hybrid), and LLM-powered chat. Includes AI Infra capabilities: pluggable model providers (Ollama/API), distributed tracing (OpenTelemetry), Prometheus metrics, model A/B testing, rate limiting, circuit breaker, and Kubernetes deployment.

## Tech Stack

- **Web:** FastAPI + Uvicorn
- **Primary DB:** PostgreSQL (prod) / SQLite (dev), via SQLAlchemy + Alembic
- **Vector DB:** LanceDB with PyArrow schemas
- **Task Queue:** Celery with Redis broker
- **Cache:** Redis (JSON serialization, SHA256 keys, namespace invalidation)
- **Model Serving:** Ollama (local GPU) or any OpenAI-compatible API (DeepSeek, vLLM, etc.)
- **Embeddings:** Ollama (`nomic-embed-text`), sentence-transformers, or deterministic local hash
- **LLM:** Pluggable via `LLM_PROVIDER` — supports `ollama`, `api` (OpenAI-compatible), `ab_test`
- **Observability:** OpenTelemetry (Jaeger), Prometheus metrics
- **Deployment:** Docker Compose (dev), Kubernetes manifests (prod)
- **Document Processing:** PyPDF, plain text, markdown, source code (.py, .rs)

## Common Commands

```bash
# Run API server locally (SQLite mode)
uvicorn app.main:app --host 127.0.0.1 --port 8000

# Run with Docker Compose (PostgreSQL + Redis + Ollama + Jaeger)
docker-compose up

# Database migrations
alembic upgrade head
alembic downgrade -1

# Run Celery worker
celery -A app.workers.celery_app worker --loglevel=info

# Tests
pytest tests/
pytest tests/test_llm_service.py        # single file

# Load demo data
python scripts/load_demo_docs.py

# Evaluation & benchmarking
python scripts/evaluate_retrieval.py
python scripts/benchmark.py

# Kubernetes deployment
kubectl apply -f k8s/
```

## Architecture

### Request Flow

Upload → `routes_docs` → `DocumentService` → Celery `ingest_task` → `chunk_service` (extract + chunk) → Celery `embed_task` → `embedding_service` → LanceDB

Search → `routes_query` → `retrieval_service` (orchestrates vector/lexical/hybrid) → cache check → LanceDB vector search and/or `bm25_service` → `hybrid_service` (RRF fusion) → `rerank_service` → response

Chat → `routes_query` → retrieval pipeline → `llm_service` → `provider_registry` → LLMProvider (Ollama/API/A/B) → grounded answer

### Key Layers

- **API routers** (`app/api/`): `routes_docs.py`, `routes_query.py`, `routes_tasks.py`, `routes_infra.py`
- **Infra layer** (`app/infra/`): Model provider abstraction and AI Infra capabilities
  - `model_provider.py`: ABC for `LLMProvider` and `EmbeddingProvider`
  - `ollama_provider.py`: Ollama REST API implementation (chat + embed)
  - `api_provider.py`: OpenAI-compatible API implementation (DeepSeek, vLLM, etc.)
  - `provider_registry.py`: Singleton registry, A/B testing provider, provider routing
  - `tracing.py`: OpenTelemetry initialization and span helpers
  - `rate_limiter.py`: Token bucket rate limiting middleware
  - `circuit_breaker.py`: Three-state circuit breaker for fault tolerance
- **Services** (`app/services/`): Business logic. `retrieval_service.py` is the core search orchestrator combining vector, BM25, and hybrid modes via RRF.
- **Workers** (`app/workers/`): Celery tasks for ingestion (`ingestion_tasks.py`) and embedding (`embedding_tasks.py`). Set `CELERY_TASK_ALWAYS_EAGER=true` for synchronous dev mode.
- **DB layer** (`app/db/`): `postgres.py` (SQLAlchemy engine/sessions), `lancedb_client.py` (vector ops), `redis_client.py`
- **Models** (`app/models/`): SQLAlchemy ORM — `Document` → `Chunk` (cascade), `Task` tracks async job state
- **Schemas** (`app/schemas/`): Pydantic request/response models
- **Config** (`app/core/config.py`): pydantic-settings, all config via env vars

### Model Provider Architecture

```
LLM_PROVIDER env var
    ├── "ollama"    → OllamaLLMProvider (local Ollama REST API)
    ├── "api"       → APILLMProvider (OpenAI-compatible: DeepSeek, vLLM, etc.)
    ├── "deepseek"  → APILLMProvider (alias)
    └── "ab_test"   → ABTestingLLMProvider (wraps two Ollama providers with traffic split)

EMBEDDING_PROVIDER env var
    ├── "ollama"    → OllamaEmbeddingProvider (Ollama /api/embed)
    └── "legacy"    → Local hash or sentence-transformers (in-process)
```

### Infra Endpoints

- `GET /api/v1/infra/models` — List loaded models and health status
- `GET /api/v1/infra/models/health` — Deep health check for all model services
- `POST /api/v1/infra/ab/config` — Dynamically adjust A/B traffic split
- `GET /api/v1/infra/ab/stats` — A/B test statistics (per-model latency, tokens)
- `GET /api/v1/infra/metrics/models` — Model-level metrics summary

### Health Checks

- `GET /health` — Shallow liveness probe (K8s liveness)
- `GET /health/ready` — Deep readiness probe: DB + Redis + model services (K8s readiness)

### Retrieval Modes

- **vector**: Cosine similarity search against LanceDB embeddings
- **lexical**: BM25 scoring via `bm25_service` (TF-IDF with configurable k1/b)
- **hybrid**: RRF fusion combining vector + lexical results

### Data Deduplication

Documents are deduplicated by SHA256 content hash before ingestion.

## Environment Configuration

Copy `.env.example` to `.env`. Key variables:

- **Core:** `DATABASE_URL`, `REDIS_URL`, `EMBEDDING_BACKEND`, `EMBEDDING_DIM`, `CHUNK_SIZE`, `CHUNK_OVERLAP`
- **LLM Provider:** `LLM_PROVIDER` (`ollama`/`api`/`deepseek`/`ab_test`), `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`
- **Ollama:** `OLLAMA_BASE_URL`, `OLLAMA_LLM_MODEL`, `OLLAMA_EMBED_MODEL`
- **Embedding:** `EMBEDDING_PROVIDER` (`ollama`/`legacy`)
- **A/B Testing:** `AB_MODEL_A`, `AB_MODEL_B`, `AB_TRAFFIC_SPLIT`
- **Rate Limiting:** `RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS_PER_MINUTE`
- **Tracing:** `OTEL_ENABLED`, `OTEL_EXPORTER_ENDPOINT`, `OTEL_SERVICE_NAME`
