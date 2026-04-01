from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document


class ChunkService:
    def extract_text(self, file_path: str) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".rs", ".py"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        raise ValueError(f"unsupported file type: {suffix}")

    def chunk_text(self, text: str, source: str) -> list[dict[str, int | str]]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []

        chunks: list[dict[str, int | str]] = []
        start = 0
        chunk_index = 0
        while start < len(cleaned):
            end = min(len(cleaned), start + settings.chunk_size)
            piece = cleaned[start:end].strip()
            if piece:
                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "content": piece,
                        "token_count": len(piece.split()),
                        "char_count": len(piece),
                        "source": source,
                    }
                )
                chunk_index += 1
            if end == len(cleaned):
                break
            start = max(0, end - settings.chunk_overlap)
        return chunks

    def replace_document_chunks(self, db: Session, document_id: str, chunks: list[dict[str, int | str]]) -> list[Chunk]:
        db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        db.commit()

        rows: list[Chunk] = []
        for chunk in chunks:
            row = Chunk(
                document_id=document_id,
                chunk_index=int(chunk["chunk_index"]),
                content=str(chunk["content"]),
                token_count=int(chunk["token_count"]),
                char_count=int(chunk["char_count"]),
                source=str(chunk["source"]),
                status="pending",
            )
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
        return rows

    def get_document_chunks(self, db: Session, document_id: str) -> list[Chunk]:
        stmt = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index.asc())
        return list(db.scalars(stmt))

    def get_searchable_chunks(
        self,
        db: Session,
        *,
        knowledge_base: str | None = None,
        document_id: str | None = None,
    ) -> list[Chunk]:
        stmt = select(Chunk).join(Document).where(Chunk.status == "indexed", Document.status == "indexed")
        if knowledge_base:
            stmt = stmt.where(Document.knowledge_base == knowledge_base)
        if document_id:
            stmt = stmt.where(Chunk.document_id == document_id)
        stmt = stmt.order_by(Chunk.created_at.desc())
        return list(db.scalars(stmt))
