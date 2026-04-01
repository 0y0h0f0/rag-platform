from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Distributed RAG Retrieval Platform"
    api_prefix: str = "/api/v1"

    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"
    lancedb_uri: str = "./data/lancedb"
    lancedb_table: str = "chunks"

    database_url: str = "sqlite:///./data/app.db"
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)


settings = Settings()
