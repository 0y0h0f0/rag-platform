from __future__ import annotations


class HybridSearchService:
    def fuse(self, vector_hits: list[dict], lexical_hits: list[dict], top_k: int) -> list[dict]:
        merged: dict[str, dict] = {}

        for rank, hit in enumerate(vector_hits, start=1):
            item = dict(hit)
            item["vector_score"] = hit["score"]
            item["lexical_score"] = 0.0
            item["score"] = 1.0 / (60 + rank)
            merged[hit["chunk_id"]] = item

        for rank, hit in enumerate(lexical_hits, start=1):
            if hit["chunk_id"] in merged:
                merged[hit["chunk_id"]]["lexical_score"] = hit["score"]
                merged[hit["chunk_id"]]["score"] += 1.0 / (60 + rank)
            else:
                item = dict(hit)
                item["vector_score"] = 0.0
                item["lexical_score"] = hit["score"]
                item["score"] = 1.0 / (60 + rank)
                merged[hit["chunk_id"]] = item

        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:top_k]
