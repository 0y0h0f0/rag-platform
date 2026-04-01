import hashlib
from pathlib import Path

from app.db.postgres import SessionLocal, init_db
from app.services.chunk_service import ChunkService
from app.services.document_service import DocumentService
from app.services.retrieval_service import RetrievalService


def main() -> None:
    base = Path("./data/demo_docs")
    base.mkdir(parents=True, exist_ok=True)

    docs = {
        "distributed_systems.txt": "Distributed systems require coordination, fault tolerance, and observability. Message queues decouple slow background work from online request paths.",
        "rag_notes.txt": "RAG systems typically include chunking, embedding, retrieval, reranking, and answer synthesis. Retrieval quality is improved by metadata filtering and reranking.",
        "lancedb_notes.txt": "LanceDB supports vector retrieval for AI applications. Hybrid search combines semantic ranking with lexical scoring for technical corpora.",
    }

    init_db()
    db = SessionLocal()
    document_service = DocumentService()
    chunk_service = ChunkService()
    retrieval_service = RetrievalService()

    for filename, content in docs.items():
        path = base / filename
        path.write_text(content, encoding="utf-8")
        document = document_service.create_document(
            db,
            filename=filename,
            storage_path=str(path),
            content_type="text/plain",
            file_size=len(content.encode("utf-8")),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            knowledge_base="demo",
        )
        chunks = chunk_service.chunk_text(content, source=str(path))
        rows = chunk_service.replace_document_chunks(db, document.id, chunks)
        retrieval_service.index_chunks(db, rows)
        document_service.update_document_status(db, document.id, "indexed")

    db.close()
    print("demo documents indexed")


if __name__ == "__main__":
    main()
