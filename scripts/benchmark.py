import statistics
import time

import httpx


def main() -> None:
    client = httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False)
    modes = ["vector", "lexical", "hybrid"]
    total = 20

    for mode in modes:
        payload = {
            "query": "How does asynchronous ingestion improve throughput?",
            "top_k": 5,
            "use_rerank": True,
            "search_mode": mode,
            "knowledge_base": "demo",
        }

        latencies = []
        for _ in range(total):
            start = time.perf_counter()
            response = client.post("/api/v1/search", json=payload)
            response.raise_for_status()
            latencies.append(time.perf_counter() - start)

        avg = sum(latencies) / total
        p95 = statistics.quantiles(latencies, n=20)[-1]
        print(f"mode={mode} requests={total} avg={avg:.4f}s p95={p95:.4f}s")


if __name__ == "__main__":
    main()
