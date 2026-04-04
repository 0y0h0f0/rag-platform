from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Distributed RAG Retrieval Platform"
    api_prefix: str = "/api/v1"

    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"
    lancedb_uri: str = "./data/lancedb"
    lancedb_table: str = "chunks"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/rag_platform"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_always_eager: bool = True

    chunk_size: int = 600
    chunk_overlap: int = 100
    embedding_dim: int = 64
    embedding_backend: str = "local"
    embedding_model_name: str = "BAAI/bge-small-zh-v1.5"

    top_k_default: int = 5
    search_mode_default: str = "vector"
    search_cache_ttl_seconds: int = 300

    # --- LLM (OpenAI-compatible API) ---
    llm_provider: str = "api"  # ollama | api | deepseek | ab_test
    llm_api_key: str = "dummy"
    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 512
    llm_timeout_seconds: float = 120.0

    # --- Ollama ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    ollama_embed_model: str = "nomic-embed-text"

    # --- Provider selection ---
    embedding_provider: str = "legacy"  # ollama | legacy (sentence_transformers / local)

    # --- A/B testing ---
    ab_model_a: str = "qwen2.5:7b"
    ab_model_b: str = "qwen2.5:3b"
    ab_traffic_split: float = 0.8

    # --- Rate limiting ---
    rate_limit_requests_per_minute: int = 30
    rate_limit_enabled: bool = True

    # --- OpenTelemetry ---
    otel_enabled: bool = False
    otel_exporter_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "rag-platform"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)


settings = Settings()
