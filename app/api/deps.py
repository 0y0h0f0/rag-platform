from app.services.chunk_service import ChunkService
from app.services.bm25_service import BM25Service
from app.services.document_service import DocumentService, TaskService
from app.services.hybrid_service import HybridSearchService
from app.services.llm_service import LLMService
from app.services.rerank_service import RerankService
from app.services.retrieval_service import RetrievalService


def get_document_service() -> DocumentService:
    return DocumentService()


def get_task_service() -> TaskService:
    return TaskService()


def get_chunk_service() -> ChunkService:
    return ChunkService()


def get_bm25_service() -> BM25Service:
    return BM25Service()


def get_retrieval_service() -> RetrievalService:
    return RetrievalService()


def get_hybrid_service() -> HybridSearchService:
    return HybridSearchService()


def get_rerank_service() -> RerankService:
    return RerankService()


def get_llm_service() -> LLMService:
    return LLMService()
