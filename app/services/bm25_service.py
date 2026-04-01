from __future__ import annotations

import math
import re
from collections import Counter

from app.models.chunk import Chunk


class BM25Service:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    def score(self, query: str, chunks: list[Chunk], top_k: int) -> list[dict]:
        query_terms = self.tokenize(query)
        if not query_terms or not chunks:
            return []

        chunk_tokens = [self.tokenize(chunk.content) for chunk in chunks]
        avgdl = sum(len(tokens) for tokens in chunk_tokens) / max(len(chunk_tokens), 1)
        doc_freq = Counter()

        for tokens in chunk_tokens:
            for term in set(tokens):
                doc_freq[term] += 1

        total_docs = len(chunks)
        scored = []
        for chunk, tokens in zip(chunks, chunk_tokens, strict=False):
            term_freq = Counter(tokens)
            doc_len = len(tokens)
            score = 0.0
            for term in query_terms:
                tf = term_freq.get(term, 0)
                if tf == 0:
                    continue
                df = doc_freq.get(term, 0)
                idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1.0 - self.b + self.b * doc_len / max(avgdl, 1.0))
                score += idf * (tf * (self.k1 + 1.0)) / max(denom, 1e-9)

            if score == 0.0:
                continue

            scored.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "text": chunk.content,
                    "source": chunk.source,
                    "chunk_index": int(chunk.chunk_index),
                    "score": float(score),
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

