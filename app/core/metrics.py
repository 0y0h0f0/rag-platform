from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response


DOCUMENT_UPLOADS = Counter(
    "rag_platform_document_upload_total",
    "Total uploaded documents",
)

DEDUPLICATED_UPLOADS = Counter(
    "rag_platform_deduplicated_upload_total",
    "Total uploads skipped by content hash deduplication",
)

SEARCH_REQUESTS = Counter(
    "rag_platform_search_requests_total",
    "Total search requests",
)

INGESTION_TASKS = Counter(
    "rag_platform_ingestion_tasks_total",
    "Total ingestion tasks",
    labelnames=("status",),
)

SEARCH_LATENCY = Histogram(
    "rag_platform_search_latency_seconds",
    "Search latency in seconds",
)

CACHE_HITS = Counter(
    "rag_platform_search_cache_hit_total",
    "Total search cache hits",
)

CACHE_MISSES = Counter(
    "rag_platform_search_cache_miss_total",
    "Total search cache misses",
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
