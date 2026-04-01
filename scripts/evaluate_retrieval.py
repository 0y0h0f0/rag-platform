from sqlalchemy.orm import Session

from app.db.postgres import SessionLocal
from app.services.retrieval_service import RetrievalService


EVAL_CASES = [
    {
        "query": "What combines semantic ranking with lexical scoring?",
        "expected": "Hybrid search combines semantic ranking with lexical scoring",
    },
    {
        "query": "Why do message queues help online systems?",
        "expected": "Message queues decouple slow background work",
    },
    {
        "query": "What improves retrieval quality in RAG systems?",
        "expected": "metadata filtering and reranking",
    },
]


def evaluate_mode(db: Session, mode: str) -> None:
    retrieval_service = RetrievalService()
    hits_at_1 = 0
    hits_at_3 = 0

    for case in EVAL_CASES:
        hits = retrieval_service.search(
            db,
            case["query"],
            top_k=3,
            knowledge_base="demo",
            search_mode=mode,
        )
        texts = [hit["text"] for hit in hits]
        if texts and case["expected"] in texts[0]:
            hits_at_1 += 1
        if any(case["expected"] in text for text in texts[:3]):
            hits_at_3 += 1

    total = len(EVAL_CASES)
    print(f"mode={mode} hit@1={hits_at_1 / total:.2f} hit@3={hits_at_3 / total:.2f}")


def main() -> None:
    db = SessionLocal()
    try:
        for mode in ("vector", "lexical", "hybrid"):
            evaluate_mode(db, mode)
    finally:
        db.close()


if __name__ == "__main__":
    main()

