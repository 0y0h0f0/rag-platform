from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: str | None = None
    knowledge_base: str | None = None
    use_rerank: bool = True
    search_mode: str = Field(default="vector", pattern="^(vector|hybrid|lexical)$")


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    source: str
    chunk_index: int
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: str | None = None
    knowledge_base: str | None = None
    use_rerank: bool = True
    search_mode: str = Field(default="vector", pattern="^(vector|hybrid|lexical)$")


class ChatResponse(BaseModel):
    query: str
    answer: str
    citations: list[SearchHit]
