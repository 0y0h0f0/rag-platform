from __future__ import annotations

import re


class RerankService:
    def rerank(self, query: str, hits: list[dict]) -> list[dict]:
        query_terms = set(re.findall(r"\w+", query.lower()))
        reranked = []
        for hit in hits:
            text_terms = set(re.findall(r"\w+", hit["text"].lower()))
            overlap = len(query_terms & text_terms)
            hit["score"] = float(hit["score"] + 0.05 * overlap)
            reranked.append(hit)
        return sorted(reranked, key=lambda item: item["score"], reverse=True)

