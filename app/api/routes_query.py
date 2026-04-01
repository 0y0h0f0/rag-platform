from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_llm_service, get_rerank_service, get_retrieval_service
from app.core.metrics import SEARCH_LATENCY, SEARCH_REQUESTS
from app.db.postgres import get_db
from app.schemas.query_schema import ChatRequest, ChatResponse, SearchHit, SearchRequest, SearchResponse
from app.services.llm_service import LLMService
from app.services.rerank_service import RerankService
from app.services.retrieval_service import RetrievalService

router = APIRouter(tags=["query"])


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    rerank_service: RerankService = Depends(get_rerank_service),
) -> SearchResponse:
    with SEARCH_LATENCY.time():
        hits = retrieval_service.search(
            db,
            payload.query,
            payload.top_k,
            payload.document_id,
            payload.search_mode,
            payload.knowledge_base,
        )
        if payload.use_rerank:
            hits = rerank_service.rerank(payload.query, hits)
    SEARCH_REQUESTS.inc()
    return SearchResponse(query=payload.query, hits=[SearchHit(**hit) for hit in hits])


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    rerank_service: RerankService = Depends(get_rerank_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatResponse:
    with SEARCH_LATENCY.time():
        hits = retrieval_service.search(
            db,
            payload.query,
            payload.top_k,
            payload.document_id,
            payload.search_mode,
            payload.knowledge_base,
        )
        if payload.use_rerank:
            hits = rerank_service.rerank(payload.query, hits)
    SEARCH_REQUESTS.inc()
    answer = llm_service.answer(payload.query, hits)
    return ChatResponse(query=payload.query, answer=answer, citations=[SearchHit(**hit) for hit in hits[: payload.top_k]])
