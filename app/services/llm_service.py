from __future__ import annotations


class LLMService:
    def answer(self, query: str, hits: list[dict]) -> str:
        if not hits:
            return "No relevant context was retrieved for the query."

        snippets = [hit["text"][:220].strip() for hit in hits[:3]]
        joined = " ".join(snippets)
        return (
            f"Question: {query}\n"
            f"Grounded summary: {joined}\n"
            "This response is generated from retrieved chunks and should be replaced by a real LLM call in production."
        )

