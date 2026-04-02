from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.lancedb_client import LanceDBClient
from app.models.chunk import Chunk
from app.services.bm25_service import BM25Service
from app.services.cache_service import CacheService
from app.services.chunk_service import ChunkService
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_service import HybridSearchService
from app.infra.tracing import trace_span


class RetrievalService:
    def __init__(self) -> None:
        self.embedding_service = EmbeddingService()
        self.lancedb = LanceDBClient()
        self.hybrid_service = HybridSearchService()
        self.chunk_service = ChunkService()
        self.bm25_service = BM25Service()
        self.cache_service = CacheService()

    def index_chunks(self, db: Session, chunks: list[Chunk]) -> int:
        rows = []
        for chunk in chunks:
            knowledge_base = chunk.document.knowledge_base if chunk.document else "default"
            rows.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "knowledge_base": knowledge_base,
                    "text": chunk.content,
                    "vector": self.embedding_service.embed_text(chunk.content),
                    "source": chunk.source,
                    "chunk_index": chunk.chunk_index,
                }
            )
            chunk.status = "indexed"
            db.add(chunk)

        db.commit()
        self.lancedb.add_chunks(rows)
        return len(rows)

    def search(
        self,
        db: Session,
        query: str,
        top_k: int,
        document_id: str | None = None,
        search_mode: str = "vector",
        knowledge_base: str | None = None,
    ) -> list[dict]:
        with trace_span("retrieval.search", {"search_mode": search_mode, "top_k": top_k}):
            cache_payload = {
                "query": query,
                "top_k": top_k,
                "document_id": document_id,
                "search_mode": search_mode,
                "knowledge_base": knowledge_base,
            }
            cached = self.cache_service.get_json("search", cache_payload)
            if cached is not None:
                return cached

            if search_mode == "lexical":
                chunks = self.chunk_service.get_searchable_chunks(
                    db,
                    knowledge_base=knowledge_base,
                    document_id=document_id,
                )
                hits = self.bm25_service.score(query, chunks, top_k)
                self.cache_service.set_json("search", cache_payload, hits)
                return hits

            vector_hits = self._vector_search(query, top_k, document_id, knowledge_base)
            if search_mode == "hybrid":
                chunks = self.chunk_service.get_searchable_chunks(
                    db,
                    knowledge_base=knowledge_base,
                    document_id=document_id,
                )
                lexical_hits = self.bm25_service.score(query, chunks, top_k)
                hits = self.hybrid_service.fuse(vector_hits, lexical_hits, top_k)
                self.cache_service.set_json("search", cache_payload, hits)
                return hits

            self.cache_service.set_json("search", cache_payload, vector_hits)
            return vector_hits

    def _vector_search(
        self,
        query: str,
        top_k: int,
        document_id: str | None = None,
        knowledge_base: str | None = None,
    ) -> list[dict]:
        query_vector = self.embedding_service.embed_text(query)
        results = self.lancedb.search(
            query_vector=query_vector,
            top_k=top_k,
            document_id=document_id,
            knowledge_base=knowledge_base,
        )
        normalized = []
        for row in results:
            distance = float(row.get("_distance", 0.0))
            normalized.append(
                {
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "text": row["text"],
                    "source": row["source"],
                    "chunk_index": int(row["chunk_index"]),
                    "score": 1.0 / (1.0 + distance),
                }
            )
        return normalized
