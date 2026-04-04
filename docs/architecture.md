# RAG Platform 架构设计文档

## 1. 系统总览

### 1.1 高层架构图

```
                              ┌────────────────────────────────────────────┐
                              │              客户端 / 前端                  │
                              └────────────────┬───────────────────────────┘
                                               │ HTTP (REST API)
                              ┌────────────────▼───────────────────────────┐
                              │          FastAPI 应用 (Uvicorn)             │
                              │  ┌──────────────────────────────────────┐  │
                              │  │  RateLimitMiddleware (Token Bucket)  │  │
                              │  │  OpenTelemetry FastAPI Instrumentation│  │
                              │  └──────────────────────────────────────┘  │
                              │                                            │
                              │  ┌─────────┬──────────┬─────────┬───────┐ │
                              │  │ routes  │ routes   │ routes  │routes │ │
                              │  │ _docs   │ _query   │ _tasks  │_infra │ │
                              │  └────┬────┴────┬─────┴────┬────┴───┬───┘ │
                              └───────┼─────────┼──────────┼────────┼─────┘
                                      │         │          │        │
                 ┌────────────────────┼─────────┼──────────┘        │
                 │                    │         │                   │
    ┌────────────▼──────────┐ ┌──────▼─────────▼──────┐  ┌────────▼──────────┐
    │   Document Service    │ │  Retrieval Service     │  │  Provider Registry │
    │   Task Service        │ │  ┌─────────────────┐   │  │  (Singleton)       │
    │                       │ │  │ EmbeddingService │   │  │  ┌──────────────┐ │
    │                       │ │  │ BM25Service      │   │  │  │ LLM Provider │ │
    │                       │ │  │ HybridService    │   │  │  │ Embed Prov.  │ │
    │                       │ │  │ RerankService    │   │  │  └──────────────┘ │
    │                       │ │  │ CacheService     │   │  │  ABTestingLLM     │
    │                       │ │  │ LLMService       │   │  │  CircuitBreaker   │
    │                       │ │  └─────────────────┘   │  └───────────────────┘
    └───────────┬───────────┘ └──────────┬─────────────┘
                │                        │
    ┌───────────▼───────────┐            │
    │  Celery Workers       │            │
    │  ┌─────────────────┐  │            │
    │  │ ingest_document  │──┼────────────┘
    │  │ embed_document   │  │
    │  └─────────────────┘  │
    └───────────┬───────────┘
                │
    ┌───────────▼───────────────────────────────────────────┐
    │                    数据层                               │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
    │  │ PostgreSQL   │  │   LanceDB    │  │    Redis     │ │
    │  │ (SQLAlchemy) │  │  (向量存储)   │  │  (缓存/队列)  │ │
    │  │ Documents    │  │  PyArrow     │  │  SHA256 Key  │ │
    │  │ Chunks       │  │  Schema      │  │  JSON Value  │ │
    │  │ Tasks        │  │              │  │              │ │
    │  └──────────────┘  └──────────────┘  └──────────────┘ │
    └───────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
    │   Ollama       │ │ DeepSeek   │ │   Jaeger    │
    │ (本地 GPU 推理) │ │ (云端 API) │ │ (链路追踪)   │
    └────────────────┘ └────────────┘ └─────────────┘
```

### 1.2 设计哲学

本平台的核心设计理念可以概括为以下几点：

**可插拔的 Provider 抽象**：通过抽象基类 `LLMProvider` 和 `EmbeddingProvider` 将模型推理与业务逻辑解耦。新增模型后端（Ollama、DeepSeek、OpenAI、vLLM）只需实现接口，业务层零改动。

**双数据库分离**：关系型数据（文档元数据、分块信息、任务状态）存储在 PostgreSQL，向量数据存储在 LanceDB。两者各司其职，避免在一个存储引擎中同时处理结构化查询和向量检索。

**异步任务驱动的入库流水线**：文档上传后立即返回 202，实际的分块和向量化由 Celery 异步任务完成。这使得 API 响应时间不受文档大小影响，同时具备重试和失败追踪能力。

**AI Infra 作为独立层**：限流、熔断、链路追踪、A/B 测试等基础设施能力被抽象到 `app/infra/` 层，与业务逻辑正交，可独立演进。

---

## 2. 分层架构

### 2.1 总体分层

```
┌─────────────────────────────────────────────────────┐
│                 API 路由层 (app/api/)                 │
│  routes_docs | routes_query | routes_tasks | routes_infra
├─────────────────────────────────────────────────────┤
│              AI Infra 层 (app/infra/)                │
│  model_provider | ollama_provider | api_provider     │
│  provider_registry | tracing | rate_limiter          │
│  circuit_breaker                                     │
├─────────────────────────────────────────────────────┤
│              业务逻辑层 (app/services/)               │
│  retrieval_service | llm_service | embedding_service │
│  bm25_service | hybrid_service | rerank_service      │
│  chunk_service | document_service | cache_service    │
├─────────────────────────────────────────────────────┤
│            异步任务层 (app/workers/)                  │
│  celery_app | ingestion_tasks | embedding_tasks      │
├─────────────────────────────────────────────────────┤
│            数据访问层 (app/db/)                       │
│  postgres.py | lancedb_client.py | redis_client.py   │
├─────────────────────────────────────────────────────┤
│            数据模型层 (app/models/)                   │
│  Document | Chunk | TaskRecord                       │
└─────────────────────────────────────────────────────┘
```

### 2.2 API 路由层

路由层是系统的入口，负责 HTTP 协议处理、请求校验（Pydantic schema）和依赖注入。

| 路由模块 | 前缀 | 职责 |
|---------|------|------|
| `routes_docs.py` | `/api/v1/documents` | 文档上传、列表、详情、删除、仪表盘统计 |
| `routes_query.py` | `/api/v1` | `/search` 检索和 `/chat` 问答 |
| `routes_tasks.py` | `/api/v1` | 异步任务状态查询 |
| `routes_infra.py` | `/api/v1/infra` | 模型列表、健康检查、A/B 测试配置与统计、模型指标 |

**路由层设计原则**：
- 路由函数本身不包含业务逻辑，通过 `Depends()` 注入 Service 实例
- 所有请求/响应通过 `app/schemas/` 下的 Pydantic model 校验
- Prometheus 指标在路由层采集（如 `SEARCH_LATENCY`、`DOCUMENT_UPLOADS`）

```python
# 典型路由结构 (routes_query.py)
@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    rerank_service: RerankService = Depends(get_rerank_service),
) -> SearchResponse:
    with SEARCH_LATENCY.time():
        hits = retrieval_service.search(db, payload.query, ...)
        if payload.use_rerank:
            hits = rerank_service.rerank(payload.query, hits)
    SEARCH_REQUESTS.inc()
    return SearchResponse(query=payload.query, hits=[SearchHit(**hit) for hit in hits])
```

### 2.3 AI Infra 层

AI Infra 层是本平台的核心差异化设计，提供模型推理基础设施能力。

#### 2.3.1 model_provider.py — 抽象基类

定义了两个核心抽象：

```python
class LLMProvider(ABC):
    @abstractmethod
    def chat_completion(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse: ...
    @abstractmethod
    def health_check(self) -> bool: ...
    @property
    @abstractmethod
    def provider_name(self) -> str: ...
    @property
    @abstractmethod
    def model_name(self) -> str: ...

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    @abstractmethod
    def health_check(self) -> bool: ...
```

`LLMResponse` 是统一的返回数据类，包含 `content`、`model`、`prompt_tokens`、`completion_tokens`、`total_tokens`、`metadata` 字段。`metadata` 字典用于扩展信息传递（如 A/B 测试中标记实际使用的模型）。

#### 2.3.2 ollama_provider.py — 本地 GPU 推理

通过 Ollama REST API 实现本地模型推理：

| 操作 | API 端点 | 说明 |
|------|---------|------|
| LLM 推理 | `POST /api/chat` | 传入 messages，返回 completion |
| 向量化 | `POST /api/embed` | 批量文本向量化 |
| 健康检查 | `GET /api/tags` | 检查目标模型是否已加载 |
| 模型预热 | `POST /api/chat` (短请求) | 启动时触发模型加载到 GPU |

关键实现细节：
- 使用 `httpx.Client`（同步），每次请求创建新连接（`trust_env=False` 避免代理干扰）
- `stream: False` 获取完整响应，简化 token 统计
- Ollama 返回的 token 统计字段为 `prompt_eval_count` / `eval_count`，与 OpenAI 格式不同
- 每次推理都通过 Prometheus `MODEL_INFERENCE_LATENCY` 和 `MODEL_INFERENCE_TOKENS` 采集指标

#### 2.3.3 api_provider.py — OpenAI 兼容 API

支持任何 OpenAI 兼容的云端 API（DeepSeek、OpenAI、vLLM serving 等）：

```
POST {base_url}/chat/completions
Headers: Authorization: Bearer {api_key}
Body: { model, messages, temperature, max_tokens }
```

与 Ollama Provider 的关键差异：
- 需要 API Key 认证
- 请求格式为 OpenAI 标准格式（`temperature`、`max_tokens` 作为顶层字段而非 `options` 嵌套）
- 健康检查通过 `GET /models` 端点

#### 2.3.4 provider_registry.py — 注册中心

ProviderRegistry 是**线程安全的单例模式**（Double-Checked Locking）：

```python
class ProviderRegistry:
    _instance: ProviderRegistry | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._init_providers()
        return cls._instance
```

Provider 选择策略：

```
llm_provider 配置值:
  "ollama"    → OllamaLLMProvider
  "ab_test"   → ABTestingLLMProvider(OllamaA, OllamaB)
  其他("api"/"deepseek") → APILLMProvider

embedding_provider 配置值:
  "ollama"    → OllamaEmbeddingProvider
  其他("legacy") → _LegacyEmbeddingProvider (包装原有 EmbeddingService)
```

`_LegacyEmbeddingProvider` 是一个适配器，将旧版的 `EmbeddingService`（支持 `local` hash 和 `sentence-transformers`）适配为 `EmbeddingProvider` 接口，实现向后兼容。

**ABTestingLLMProvider** 实现流量分割：

```python
class ABTestingLLMProvider(LLMProvider):
    def _pick_provider(self) -> LLMProvider:
        return self._provider_a if random.random() < self._split else self._provider_b

    def chat_completion(self, messages, **kwargs) -> LLMResponse:
        provider = self._pick_provider()
        start = time.perf_counter()
        response = provider.chat_completion(messages, **kwargs)
        elapsed = time.perf_counter() - start
        # 线程安全地记录统计
        with self._lock:
            stats = self._stats[provider.model_name]
            stats.requests += 1
            stats.total_latency += elapsed
            stats.total_tokens += response.total_tokens
        response.metadata["ab_model"] = provider.model_name
        return response
```

统计数据通过 `get_stats()` 暴露给 `/api/v1/infra/ab/stats` 端点，流量比例通过 `/api/v1/infra/ab/config` 动态调整，无需重启。

#### 2.3.5 tracing.py — 链路追踪

基于 OpenTelemetry 标准实现分布式追踪：

```
初始化链路:
  Resource("rag-platform")
    → TracerProvider
      → BatchSpanProcessor
        → OTLPSpanExporter (gRPC)
          → Jaeger (localhost:4317)
```

关键设计：
- **优雅降级**：OTel 包未安装时回退到 `_NoOpTracer` / `_NoOpSpan`，业务代码零侵入
- **trace_span 上下文管理器**：业务代码中统一使用，不直接依赖 OTel API
- **Celery 链路传播**：`inject_trace_context()` 将当前 trace context 序列化为 dict，通过 Celery task headers 传递；worker 端通过 `extract_trace_context()` 恢复

```python
# 业务代码中使用
with trace_span("retrieval.search", {"search_mode": search_mode, "top_k": top_k}):
    # 搜索逻辑...

# Celery 任务中使用
with trace_span("celery.ingest_document", {"document_id": document_id}):
    # 入库逻辑...
```

Span 层次结构：

```
HTTP Request (FastAPI Instrumentation)
  └── retrieval.search
        ├── embedding (向量化 query)
        ├── lancedb.search (向量检索)
        └── bm25.score (词法检索, 仅 hybrid 模式)
  └── llm.chat_completion (仅 /chat 端点)

celery.ingest_document
  └── chunk.extract
  └── chunk.split
  └── celery.embed_document
        └── embedding.batch
        └── lancedb.add
```

#### 2.3.6 rate_limiter.py — 限流器

实现了 **Token Bucket（令牌桶）** 算法：

```python
class TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self._rate = rate          # 令牌填充速率 (tokens/秒)
        self._capacity = capacity  # 桶容量 (最大突发)
        self._tokens = capacity    # 当前令牌数
        self._last_refill = time.monotonic()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
```

作为 FastAPI Middleware 注入，对所有 API 请求生效。跳过 `/health`、`/health/ready`、`/metrics` 等运维端点。超限时返回 `429 Too Many Requests` 并递增 `RATE_LIMIT_REJECTED` Prometheus 指标。

配置项：`RATE_LIMIT_REQUESTS_PER_MINUTE`（默认 30）、`RATE_LIMIT_ENABLED`（默认 true）。

#### 2.3.7 circuit_breaker.py — 熔断器

经典三态熔断器实现：

```
         连续失败 >= threshold
  CLOSED ─────────────────────→ OPEN
    ▲                             │
    │ 调用成功                     │ 等待 recovery_timeout
    │                             ▼
  HALF_OPEN ◄─────────────────── OPEN
    │
    │ 调用失败
    └──────────────────────────→ OPEN
```

关键参数：
- `failure_threshold`: 连续失败多少次后打开熔断（默认 5）
- `recovery_timeout`: 打开后等待多少秒尝试半开（默认 30s）
- `half_open_max_calls`: 半开状态最多允许多少次试探调用（默认 1）

使用方式：

```python
breaker = CircuitBreaker(name="ollama-llm", failure_threshold=5, recovery_timeout=30.0)
try:
    result = breaker.call(provider.chat_completion, messages)
except CircuitBreakerOpen:
    # 快速失败，不再访问下游
    return fallback_response()
```

### 2.4 业务逻辑层

#### 2.4.1 retrieval_service.py — 检索编排器

`RetrievalService` 是搜索流程的核心编排者，聚合了所有检索相关的子服务：

```python
class RetrievalService:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.lancedb = LanceDBClient()
        self.hybrid_service = HybridSearchService()
        self.chunk_service = ChunkService()
        self.bm25_service = BM25Service()
        self.cache_service = CacheService()
```

搜索流程决策树：

```
search(query, mode)
  │
  ├── 查询缓存 → 命中 → 返回
  │
  ├── mode == "lexical"
  │     └── 从 PostgreSQL 加载 chunks → BM25 评分 → 缓存 → 返回
  │
  ├── mode == "vector"
  │     └── query 向量化 → LanceDB 余弦搜索 → 距离→分数转换 → 缓存 → 返回
  │
  └── mode == "hybrid"
        ├── query 向量化 → LanceDB 余弦搜索 (vector_hits)
        ├── 从 PostgreSQL 加载 chunks → BM25 评分 (lexical_hits)
        └── RRF 融合 (vector_hits + lexical_hits) → 缓存 → 返回
```

向量搜索的距离→分数转换公式：`score = 1.0 / (1.0 + distance)`，将余弦距离映射到 (0, 1] 区间。

#### 2.4.2 llm_service.py — 大模型服务

负责构建 RAG prompt 并调用 LLM 生成回答：

```python
class LLMService:
    def _build_messages(self, query, hits):
        # System prompt: 知识库 QA 角色设定
        # User prompt: 问题 + 检索上下文（最多 5 条）
        return [
            {"role": "system", "content": "你是一个面向知识库问答场景的中文 AI 助手..."},
            {"role": "user", "content": f"问题：{query}\n检索上下文：\n{context}"},
        ]

    def answer_with_metadata(self, query, hits):
        # 通过 ProviderRegistry 获取 LLM → 调用 chat_completion
        # 返回 answer + model_version (用于 A/B 分析)
```

`answer_with_metadata` 方法额外返回 `model_version`，当使用 A/B 测试时可追踪每个回答由哪个模型生成。

#### 2.4.3 其他 Service

| Service | 职责 |
|---------|------|
| `embedding_service.py` | 文本向量化，支持 `local`（确定性 hash）和 `sentence-transformers` 两种后端 |
| `bm25_service.py` | BM25 词法检索评分，参数 k1=1.5, b=0.75，正则分词 `\w+` |
| `hybrid_service.py` | RRF（Reciprocal Rank Fusion）融合，常数 k=60 |
| `rerank_service.py` | 检索结果重排序 |
| `chunk_service.py` | 文档文本提取（PDF、txt、md、py、rs）和滑动窗口分块 |
| `document_service.py` | 文档 CRUD、SHA256 去重、仪表盘统计 |
| `cache_service.py` | Redis 缓存封装（详见第 7 节） |

### 2.5 异步任务层

基于 Celery + Redis Broker 实现异步任务流水线：

```python
# celery_app.py 配置
celery_app = Celery("rag-platform")
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_always_eager=settings.celery_task_always_eager,  # dev 模式下同步执行
)
```

**ingest_document 任务**（`ingestion_tasks.py`）：
1. 更新文档状态为 `processing`
2. 提取原始文本 (`chunk_service.extract_text`)
3. 滑动窗口分块 (`chunk_service.chunk_text`)
4. 持久化分块到 PostgreSQL (`chunk_service.replace_document_chunks`)
5. 清除搜索缓存
6. 触发下游 `embed_document` 任务

**embed_document 任务**（`embedding_tasks.py`）：
1. 从 PostgreSQL 读取文档的所有 chunks
2. 调用 `retrieval_service.index_chunks` 进行向量化并写入 LanceDB
3. 清除搜索缓存
4. 更新文档状态为 `indexed`，任务状态为 `completed`

两个任务都包裹在 `trace_span` 中实现链路追踪，且都有 try/except 错误处理，失败时更新文档和任务状态为 `failed`。

**开发模式**：设置 `CELERY_TASK_ALWAYS_EAGER=true` 时任务同步执行，无需启动 Redis 和 Celery Worker。

### 2.6 数据访问层

#### postgres.py

```python
# SQLite (dev) / PostgreSQL (prod) 自动切换
connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

通过 `get_db()` 生成器函数提供 Session，配合 FastAPI `Depends` 实现请求级别的 Session 生命周期管理。

#### lancedb_client.py

```python
class LanceDBClient:
    def ensure_table(self):
        schema = pa.schema([
            pa.field("chunk_id", pa.string()),
            pa.field("document_id", pa.string()),
            pa.field("knowledge_base", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), settings.embedding_dim)),
            pa.field("source", pa.string()),
            pa.field("chunk_index", pa.int32()),
        ])
        self.db.create_table(self.table_name, schema=schema)
```

支持按 `document_id` 和 `knowledge_base` 过滤的向量搜索，以及按 `document_id` 批量删除。

#### redis_client.py

提供 `get_redis()`（直接连接）和 `get_redis_safe()`（连接失败返回 None 而非抛异常）两种接口。后者用于缓存层，确保 Redis 不可用时系统不会崩溃。

### 2.7 数据模型层

```
┌──────────────────────────┐
│       documents          │
├──────────────────────────┤
│ id          VARCHAR(36)  │ PK
│ filename    VARCHAR(255) │
│ content_type VARCHAR(128)│
│ storage_path TEXT         │
│ file_size   INTEGER      │
│ content_hash VARCHAR(64) │ INDEX (SHA256 去重)
│ knowledge_base VARCHAR(128)│ INDEX
│ status      VARCHAR(32)  │ uploaded → processing → indexed | failed
│ created_at  DATETIME     │
│ updated_at  DATETIME     │
└──────────┬───────────────┘
           │ 1:N (CASCADE DELETE)
┌──────────▼───────────────┐
│        chunks            │
├──────────────────────────┤
│ id          VARCHAR(36)  │ PK
│ document_id VARCHAR(36)  │ FK → documents.id (INDEX)
│ chunk_index INTEGER      │
│ content     TEXT          │
│ token_count INTEGER      │
│ char_count  INTEGER      │
│ source      VARCHAR(255) │
│ status      VARCHAR(32)  │ pending → indexed
│ created_at  DATETIME     │
└──────────────────────────┘

┌──────────────────────────┐
│        tasks             │
├──────────────────────────┤
│ id          VARCHAR(36)  │ PK
│ document_id VARCHAR(36)  │ FK → documents.id (SET NULL on delete)
│ task_type   VARCHAR(64)  │ "ingest_and_index"
│ status      VARCHAR(32)  │ pending → queued → processing → completed | failed
│ celery_task_id VARCHAR(64)│
│ error_message TEXT        │
│ retry_count INTEGER      │
│ created_at  DATETIME     │
│ finished_at DATETIME     │
└──────────────────────────┘
```

关键设计：
- Document → Chunks 使用 `cascade="all, delete-orphan"`，删除文档时自动级联删除分块
- Document → Tasks 使用 `ondelete="SET NULL"`，删除文档后任务记录保留（用于审计）
- 所有主键使用 UUID v4，适合分布式环境

---

## 3. 数据流详解

### 3.1 文档上传入库流程

```
客户端                    FastAPI                  Celery Worker
  │                         │                         │
  │  POST /documents/upload │                         │
  │ ───────────────────────>│                         │
  │                         │                         │
  │                         │ 1. 读取文件内容           │
  │                         │ 2. 计算 SHA256 hash      │
  │                         │ 3. 查询是否已存在         │
  │                         │    (content_hash + kb)   │
  │                         │                         │
  │                         │──[重复文件]──→ 返回       │
  │                         │  deduplicated 202       │
  │                         │                         │
  │                         │──[新文件]                │
  │                         │ 4. 写入磁盘              │
  │                         │ 5. 创建 Document 记录    │
  │                         │ 6. 创建 Task 记录        │
  │                         │ 7. 发送 Celery 任务      │
  │  ◄──── 202 Accepted ───│─────────────────────────>│
  │   {document_id,task_id} │                         │
  │                         │                  8. 提取文本
  │                         │                  9. 滑动窗口分块
  │                         │                 10. 存储 Chunks → PG
  │                         │                 11. 清除搜索缓存
  │                         │                 12. 触发 embed_document
  │                         │                         │
  │                         │                 13. 对每个 chunk 向量化
  │                         │                 14. 批量写入 LanceDB
  │                         │                 15. 更新状态 → indexed
  │                         │                 16. 清除搜索缓存
```

**去重机制**：上传时计算文件内容的 SHA256 hash，在相同 knowledge_base 内查找是否已存在相同 hash 的文档。若重复则直接返回已有文档 ID，不重复入库。

**文件类型支持**：`.txt`、`.md`、`.pdf`（PyPDF）、`.py`、`.rs`

### 3.2 在线检索流程

#### 3.2.1 向量检索 (vector)

```
客户端                        RetrievalService                LanceDB
  │                               │                             │
  │  POST /search                 │                             │
  │  {query, mode:"vector"}       │                             │
  │ ─────────────────────────────>│                             │
  │                               │                             │
  │                               │ 1. 查 Redis 缓存             │
  │                               │    (SHA256(query+params))   │
  │                               │                             │
  │                               │──[缓存命中]─→ 直接返回       │
  │                               │                             │
  │                               │──[缓存未命中]                │
  │                               │ 2. query → embedding_service │
  │                               │    → 得到 query_vector       │
  │                               │                             │
  │                               │ 3. lancedb.search ─────────>│
  │                               │    (query_vector, top_k,    │
  │                               │     document_id, kb filter) │
  │                               │ ◄─ 余弦距离排序结果 ─────────│
  │                               │                             │
  │                               │ 4. distance → score 转换     │
  │                               │    score = 1/(1+distance)   │
  │                               │                             │
  │                               │ 5. 写入 Redis 缓存           │
  │  ◄──── SearchResponse ────────│                             │
```

#### 3.2.2 词法检索 (lexical)

```
RetrievalService          ChunkService/PG          BM25Service
       │                        │                       │
       │ get_searchable_chunks  │                       │
       │ ─────────────────────>│                       │
       │ ◄── Chunk[] ──────────│                       │
       │                        │                       │
       │ bm25.score(query, chunks, top_k) ────────────>│
       │                        │                       │
       │                        │              1. 正则分词 (\w+)
       │                        │              2. 计算 IDF
       │                        │              3. BM25 评分 (k1=1.5, b=0.75)
       │                        │              4. 按分数降序排序
       │ ◄──── scored hits ────────────────────────────│
```

#### 3.2.3 混合检索 (hybrid)

```
RetrievalService
       │
       ├──→ _vector_search() ──→ vector_hits
       │
       ├──→ bm25_service.score() ──→ lexical_hits
       │
       └──→ hybrid_service.fuse(vector_hits, lexical_hits, top_k)
              │
              │ RRF 融合算法:
              │   对每条结果: score = Σ 1/(k + rank)
              │   k = 60 (常数)
              │
              │ 去重: 同一 chunk_id 的分数累加
              │ 排序: 按融合分数降序，取 top_k
              │
              └──→ fused_hits
```

### 3.3 Chat 问答流程

```
客户端                    routes_query          RetrievalService      LLMService
  │                          │                        │                   │
  │  POST /chat              │                        │                   │
  │  {query, mode, top_k}    │                        │                   │
  │ ────────────────────────>│                        │                   │
  │                          │                        │                   │
  │                          │ 1. search() ──────────>│                   │
  │                          │ ◄── hits[] ────────────│                   │
  │                          │                        │                   │
  │                          │ 2. rerank() (可选)      │                   │
  │                          │                        │                   │
  │                          │ 3. answer_with_metadata(query, hits) ──────>│
  │                          │                        │                   │
  │                          │                        │      4. 构建 messages:
  │                          │                        │         system: 角色设定
  │                          │                        │         user: 问题+上下文
  │                          │                        │
  │                          │                        │      5. ProviderRegistry
  │                          │                        │         .get_llm()
  │                          │                        │         .chat_completion()
  │                          │                        │
  │                          │ ◄── {answer, model_version} ────────────────│
  │                          │                        │                   │
  │  ◄── ChatResponse ──────│                        │                   │
  │  {answer, citations,     │                        │                   │
  │   model_version}         │                        │                   │
```

### 3.4 A/B 测试请求流程

```
Chat 请求 ──→ LLMService ──→ ProviderRegistry.get_llm()
                                      │
                                      ▼
                             ABTestingLLMProvider
                                      │
                              random() < split?
                             ╱                  ╲
                           是                    否
                           ▼                     ▼
                    OllamaLLMProvider      OllamaLLMProvider
                    (model_a: qwen2.5:7b)  (model_b: qwen2.5:3b)
                           │                     │
                           ▼                     ▼
                    Ollama /api/chat        Ollama /api/chat
                           │                     │
                           └────────┬────────────┘
                                    ▼
                           记录统计 (线程安全):
                             - requests++
                             - total_latency += elapsed
                             - total_tokens += tokens
                                    │
                                    ▼
                           response.metadata["ab_model"] = model_name
                                    │
                                    ▼
                           返回 LLMResponse
                                    │
              ┌─────────────────────┤
              ▼                     ▼
    ChatResponse.model_version   GET /infra/ab/stats
    (前端可展示模型版本)           {"qwen2.5:7b": {requests: 80, avg_latency: 1.2},
                                  "qwen2.5:3b": {requests: 20, avg_latency: 0.8}}

    POST /infra/ab/config {"traffic_split": 0.6}  ← 动态调整流量比例
```

---

## 4. Provider 架构详解

### 4.1 类继承关系

```
                    LLMProvider (ABC)
                   ╱       │        ╲
                  ╱        │         ╲
    OllamaLLMProvider  APILLMProvider  ABTestingLLMProvider
    (本地 Ollama)      (云端 API)       (流量分割包装器)
                                            │
                                     包装两个 LLMProvider


                  EmbeddingProvider (ABC)
                   ╱                  ╲
    OllamaEmbeddingProvider    _LegacyEmbeddingProvider
    (Ollama /api/embed)        (适配器: 包装 EmbeddingService)
```

### 4.2 Provider Registry 生命周期

```
FastAPI startup
    │
    ▼
ProviderRegistry.get_instance()
    │
    ▼ (首次调用，Double-Checked Locking)
_init_providers()
    │
    ├── _create_llm_provider()
    │     读取 settings.llm_provider
    │     实例化对应 Provider
    │
    └── _create_embedding_provider()
          读取 settings.embedding_provider
          实例化对应 Provider
    │
    ▼
日志: "providers initialized: llm=ollama/qwen2.5:7b, embedding=local/local-hash"
    │
    ▼
整个进程生命周期内复用同一实例
```

### 4.3 Ollama Provider 实现细节

**LLM 推理请求格式**：

```json
POST http://localhost:11434/api/chat
{
    "model": "qwen2.5:7b-instruct-q4_K_M",
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."}
    ],
    "stream": false,
    "options": {
        "temperature": 0.2,
        "num_predict": 512
    }
}
```

**Embedding 请求格式**：

```json
POST http://localhost:11434/api/embed
{
    "model": "nomic-embed-text",
    "input": ["text1", "text2", ...]
}
```

**健康检查**：

```json
GET http://localhost:11434/api/tags
Response: {"models": [{"name": "qwen2.5:7b-instruct-q4_K_M", ...}]}
```

检查返回的 models 列表中是否包含目标模型名称（使用 `in` 子串匹配，兼容 tag 后缀）。

### 4.4 Legacy Embedding 兼容

`_LegacyEmbeddingProvider` 作为适配器，将旧版 `EmbeddingService` 包装为 `EmbeddingProvider` 接口：

```python
class _LegacyEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        from app.services.embedding_service import EmbeddingService
        self._svc = EmbeddingService()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._svc.embed_many(texts)

    def health_check(self) -> bool:
        result = self._svc.embed_text("health check")
        return len(result) == settings.embedding_dim
```

这种设计允许渐进式迁移：先通过 Provider 接口统一调用方式，再逐步将嵌入模型迁移到 Ollama。

---

## 5. 可观测性架构

### 5.1 OpenTelemetry 追踪流水线

```
┌──────────────────────────────────────────────────────┐
│                  FastAPI 进程                          │
│                                                      │
│  FastAPIInstrumentor                                 │
│       │                                              │
│       ▼                                              │
│  TracerProvider                                      │
│    ├── Resource: {"service.name": "rag-platform"}    │
│    └── BatchSpanProcessor                            │
│          └── OTLPSpanExporter (gRPC)                 │
│                  │                                   │
└──────────────────┼───────────────────────────────────┘
                   │ gRPC (localhost:4317)
                   ▼
            ┌─────────────┐
            │   Jaeger    │
            │  Collector  │
            └─────────────┘
```

### 5.2 Span 层次结构示例

以一次 `/chat` 请求为例：

```
[trace-id: abc123]
│
├── HTTP POST /api/v1/chat                              (FastAPIInstrumentor 自动创建)
│   ├── retrieval.search                                (trace_span)
│   │   ├── attributes: {search_mode: "hybrid", top_k: 5}
│   │   ├── [内部] embedding_service.embed_text(query)
│   │   ├── [内部] lancedb.search(query_vector)
│   │   └── [内部] bm25_service.score(query, chunks)
│   │
│   └── llm.chat_completion                             (Provider 内部, Prometheus)
│       ├── provider: "ollama"
│       ├── model: "qwen2.5:7b"
│       └── latency: 1.23s
```

### 5.3 Celery 链路传播

```python
# API 端 (发送任务时)
carrier = inject_trace_context()  # 序列化当前 trace context
ingest_document.apply_async(args=[...], headers=carrier)

# Worker 端 (执行任务时)
ctx = extract_trace_context(task.request.headers)
# 在恢复的 context 下创建子 span
with trace_span("celery.ingest_document", {"document_id": doc_id}):
    ...
```

### 5.4 Prometheus 指标注册表

| 指标名 | 类型 | 标签 | 说明 |
|--------|------|------|------|
| `rag_platform_document_upload_total` | Counter | - | 文档上传总数 |
| `rag_platform_deduplicated_upload_total` | Counter | - | 去重跳过的上传数 |
| `rag_platform_search_requests_total` | Counter | - | 搜索请求总数 |
| `rag_platform_ingestion_tasks_total` | Counter | status | 入库任务数 (success/failed) |
| `rag_platform_search_latency_seconds` | Histogram | - | 搜索延迟分布 |
| `rag_platform_search_cache_hit_total` | Counter | - | 缓存命中数 |
| `rag_platform_search_cache_miss_total` | Counter | - | 缓存未命中数 |
| `rag_model_inference_seconds` | Histogram | provider, model, operation | 模型推理延迟 |
| `rag_model_tokens_total` | Counter | model, direction | Token 消耗 (input/output) |
| `rag_model_health_status` | Gauge | provider, model | 模型健康状态 (1/0) |
| `rag_rate_limit_rejected_total` | Counter | - | 限流拒绝请求数 |
| `rag_embedding_batch_size` | Histogram | - | Embedding 批大小分布 |

所有指标通过 `GET /metrics` 端点暴露，格式为 Prometheus exposition format，可直接对接 Prometheus scraper。

---

## 6. 双数据库设计

### 6.1 PostgreSQL — 结构化数据

存储文档元数据、分块文本和任务状态。

```
┌─────────────┐     1:N     ┌─────────────┐
│  documents  │ ───────────>│   chunks    │
│             │  CASCADE    │             │
│  id (PK)    │  DELETE     │  id (PK)    │
│  filename   │             │  document_id│ (FK, INDEX)
│  content_hash│ (INDEX)    │  chunk_index│
│  knowledge_base│(INDEX)   │  content    │
│  status     │             │  token_count│
│  ...        │             │  status     │
└──────┬──────┘             └─────────────┘
       │ 1:N
       │ SET NULL on delete
       ▼
┌─────────────┐
│    tasks    │
│  id (PK)    │
│  document_id│ (FK, nullable)
│  task_type  │
│  status     │
│  celery_task_id│
│  error_message│
│  retry_count│
└─────────────┘
```

**开发/生产切换**：通过 `DATABASE_URL` 环境变量切换。SQLite 时自动添加 `check_same_thread=False`。

### 6.2 LanceDB — 向量存储

PyArrow Schema 定义：

```python
schema = pa.schema([
    pa.field("chunk_id", pa.string()),          # 关联 PG chunks.id
    pa.field("document_id", pa.string()),       # 关联 PG documents.id
    pa.field("knowledge_base", pa.string()),    # 知识库隔离
    pa.field("text", pa.string()),              # 原文（用于返回）
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),  # 向量
    pa.field("source", pa.string()),            # 来源文件路径
    pa.field("chunk_index", pa.int32()),        # 块序号
])
```

LanceDB 以文件形式存储在 `./data/lancedb/`，零依赖部署，适合单机和小规模场景。

### 6.3 为什么双数据库

| 维度 | PostgreSQL | LanceDB |
|------|-----------|---------|
| 查询模式 | 精确查询、范围查询、JOIN、事务 | 近邻向量搜索 (ANN) |
| 索引类型 | B-Tree、Hash | IVF_PQ、HNSW (LanceDB 内置) |
| 一致性 | ACID 事务 | 最终一致（文件级别） |
| 适用数据 | 元数据、状态、关系 | 高维浮点向量 |
| 扩展路径 | 读写分离、分库分表 | 分片、向量数据库集群 |

将两种截然不同的查询模式放在同一存储引擎中（如仅用 PostgreSQL + pgvector）会导致：
1. 向量索引和 B-Tree 索引竞争内存
2. 向量搜索的 I/O 模式（大量随机读）影响事务性查询
3. 难以独立扩展向量搜索能力

分离后各自可以按需优化和扩展。

---

## 7. 缓存策略

### 7.1 缓存键设计

```python
class CacheService:
    def _key(self, namespace: str, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"rag-platform:{namespace}:{digest}"
```

键结构：`rag-platform:{namespace}:{sha256(params)}`

例如：`rag-platform:search:a1b2c3d4...`

**为什么用 SHA256**：
- 查询参数可能很长（query 文本），直接作为 Redis key 效率低
- SHA256 保证不同参数组合产生不同的 key（碰撞概率忽略不计）
- 固定长度 64 字符，key 大小可控

### 7.2 缓存流程

```
请求参数: {query, top_k, document_id, search_mode, knowledge_base}
       │
       ▼
  SHA256 → cache_key
       │
       ▼
  Redis GET cache_key
       │
  ┌────┴────┐
  │ 命中    │ 未命中
  │         │
  ▼         ▼
返回缓存   执行检索
           │
           ▼
         Redis SETEX cache_key TTL value
           │
           ▼
         返回结果
```

### 7.3 缓存失效

| 触发条件 | 失效方式 |
|---------|---------|
| TTL 到期 | Redis 自动过期（默认 300 秒） |
| 文档入库完成 | `cache_service.clear_namespace("search")` — 删除所有 `rag-platform:search:*` 的 key |
| 向量索引完成 | 同上 |

**命名空间失效**：使用 `KEYS rag-platform:search:*` 模式匹配后批量删除。注意：在大规模生产环境中，`KEYS` 命令可能阻塞 Redis，应替换为 `SCAN`。

### 7.4 优雅降级

`get_redis_safe()` 在连接失败时返回 `None`，`CacheService` 的所有方法在 client 为 None 时静默跳过。这意味着 Redis 不可用时系统正常运行，只是失去缓存加速。

---

## 8. 设计决策与权衡 (Trade-offs)

### 8.1 为什么选择 Ollama 而非 vLLM 做本地 GPU 推理

| 维度 | Ollama | vLLM |
|------|--------|------|
| 部署复杂度 | 单二进制，`ollama serve` 即可 | 需要 Python 环境、CUDA toolkit、编译依赖 |
| 模型管理 | `ollama pull model:tag` 类似 Docker | 手动下载 HuggingFace 权重 |
| API 兼容性 | 自有 REST API（简洁直观） | OpenAI 兼容 API |
| 量化支持 | 原生 GGUF 量化（Q4_K_M 等） | GPTQ、AWQ、SqueezeLLM |
| 吞吐量 | 单请求服务，无 continuous batching | PagedAttention + continuous batching，吞吐量远高 |
| 适用场景 | 开发、演示、低并发 | 生产、高并发 |

**决策理由**：本平台定位为学习型项目和中小规模部署。Ollama 的「开箱即用」特性大幅降低了环境搭建成本。对于需要高并发的生产环境，可以通过 `APILLMProvider` 对接 vLLM 的 OpenAI 兼容端点，无需修改业务代码。

### 8.2 为什么用 RRF 而非加权平均做混合融合

```python
# RRF (Reciprocal Rank Fusion)
score = Σ 1/(k + rank_i)    # k=60

# 加权平均 (Weighted Average)
score = α * vector_score + (1-α) * lexical_score
```

| 维度 | RRF | 加权平均 |
|------|-----|---------|
| 分数校准 | 不需要——只使用排名，对分数分布不敏感 | 需要——两种分数的量纲和分布必须可比 |
| 超参数 | 常数 k（通常固定为 60） | 权重 α（需要调优） |
| 鲁棒性 | 对单个检索器的异常分数不敏感 | 一个检索器分数异常会影响整体 |
| 理论基础 | 论文 "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods" | 直觉简单但依赖假设 |

**决策理由**：向量检索返回的是余弦距离（经 `1/(1+d)` 转换），BM25 返回的是 TF-IDF 分数，两者量纲完全不同。加权平均需要先做分数归一化，而归一化策略本身就引入了超参数。RRF 只关心排名，天然规避了这个问题。

### 8.3 为什么用 Token Bucket 而非 Sliding Window 做限流

| 维度 | Token Bucket（令牌桶） | Sliding Window（滑动窗口） |
|------|----------------------|--------------------------|
| 突发流量 | 允许——桶满时可以一次性消耗所有令牌 | 不允许——严格限制窗口内请求数 |
| 实现复杂度 | 低——一个计数器 + 时间戳 | 中等——需要记录每个请求的时间戳或使用 Redis sorted set |
| 内存开销 | O(1)——只存令牌数和上次补充时间 | O(N)——需要存储窗口内所有请求时间戳 |
| 精度 | 近似——依赖令牌补充频率 | 精确——每个请求独立计时 |
| 平滑性 | 好——请求速率自然趋向令牌补充速率 | 边界效应——窗口切换时可能出现双倍流量 |

**决策理由**：RAG 平台的使用模式是「间歇性突发」——用户可能在短时间内连续发起多次搜索和问答。Token Bucket 允许这种突发行为（消耗积攒的令牌），同时通过令牌补充速率限制长期平均请求率。Sliding Window 会对突发流量过于严格，影响用户体验。

### 8.4 为什么用进程内熔断器而非分布式熔断器

| 维度 | 进程内 (In-Memory) | 分布式 (Redis/etcd) |
|------|-------------------|-------------------|
| 延迟 | 零——纯内存操作 | 每次检查需要网络往返 |
| 一致性 | 每个进程独立判断 | 全局一致 |
| 复杂度 | 低——threading.Lock 即可 | 高——需要处理分布式锁、网络分区 |
| 适用场景 | 单进程或少量进程 | 大规模微服务集群 |

**决策理由**：

1. 本平台典型部署是单 Uvicorn 进程（或少量 worker）。进程内熔断已经足够。
2. 熔断器的核心价值是「快速失败，避免雪崩」。即使多个进程各自独立判断，也能达到这个目的——每个进程在检测到下游故障后独立停止请求，整体效果等价于全局熔断。
3. 引入 Redis 做分布式熔断反而增加了对 Redis 的依赖——如果 Redis 本身就是故障点，熔断器也跟着失效。

**潜在改进**：如果未来扩展到多节点部署且需要精确控制全局熔断状态，可以将 `CircuitBreaker` 的状态存储从内存迁移到 Redis，接口保持不变。

---

## 附录 A: 配置项速查

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/rag_platform` | 数据库连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `LLM_PROVIDER` | `deepseek` | LLM 后端: ollama / api / deepseek / ab_test |
| `EMBEDDING_PROVIDER` | `legacy` | Embedding 后端: ollama / legacy |
| `EMBEDDING_BACKEND` | `local` | Legacy 模式下: local / sentence_transformers |
| `EMBEDDING_DIM` | `64` | 向量维度 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_LLM_MODEL` | `qwen2.5:7b-instruct-q4_K_M` | Ollama LLM 模型 |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama Embedding 模型 |
| `CHUNK_SIZE` | `600` | 分块大小（字符数） |
| `CHUNK_OVERLAP` | `100` | 分块重叠（字符数） |
| `SEARCH_CACHE_TTL_SECONDS` | `300` | 搜索缓存 TTL |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | 限流阈值 |
| `OTEL_ENABLED` | `false` | 是否启用 OpenTelemetry |
| `OTEL_EXPORTER_ENDPOINT` | `http://localhost:4317` | OTLP 导出端点 |
| `AB_MODEL_A` | `qwen2.5:7b` | A/B 测试模型 A |
| `AB_MODEL_B` | `qwen2.5:3b` | A/B 测试模型 B |
| `AB_TRAFFIC_SPLIT` | `0.8` | A/B 流量分配（A 的比例） |
| `CELERY_TASK_ALWAYS_EAGER` | `true` | 开发模式同步执行任务 |

## 附录 B: 关键文件路径

```
app/
├── main.py                          # FastAPI 应用工厂
├── api/
│   ├── deps.py                      # 依赖注入工厂
│   ├── routes_docs.py               # 文档管理路由
│   ├── routes_query.py              # 搜索/问答路由
│   ├── routes_tasks.py              # 任务状态路由
│   └── routes_infra.py              # 基础设施管理路由
├── infra/
│   ├── model_provider.py            # LLMProvider / EmbeddingProvider ABC
│   ├── ollama_provider.py           # Ollama 实现
│   ├── api_provider.py              # OpenAI 兼容 API 实现
│   ├── provider_registry.py         # 单例注册中心 + ABTestingLLMProvider
│   ├── tracing.py                   # OpenTelemetry 追踪
│   ├── rate_limiter.py              # Token Bucket 限流
│   └── circuit_breaker.py           # 三态熔断器
├── services/
│   ├── retrieval_service.py         # 检索编排器
│   ├── llm_service.py               # LLM 调用 + RAG Prompt 构建
│   ├── embedding_service.py         # 向量化服务 (legacy)
│   ├── bm25_service.py              # BM25 词法检索
│   ├── hybrid_service.py            # RRF 融合
│   ├── rerank_service.py            # 重排序
│   ├── chunk_service.py             # 文本提取 + 分块
│   ├── document_service.py          # 文档 CRUD
│   └── cache_service.py             # Redis 缓存
├── workers/
│   ├── celery_app.py                # Celery 配置
│   ├── ingestion_tasks.py           # 文档入库任务
│   └── embedding_tasks.py           # 向量化任务
├── db/
│   ├── postgres.py                  # SQLAlchemy 引擎/Session
│   ├── lancedb_client.py            # LanceDB 向量操作
│   └── redis_client.py              # Redis 连接
├── models/
│   ├── document.py                  # Document ORM
│   ├── chunk.py                     # Chunk ORM
│   └── task.py                      # TaskRecord ORM
├── schemas/
│   ├── doc_schema.py                # 文档相关 Pydantic Schema
│   ├── query_schema.py              # 搜索/问答 Schema
│   └── task_schema.py               # 任务 Schema
└── core/
    ├── config.py                    # pydantic-settings 配置
    ├── logger.py                    # 日志配置
    └── metrics.py                   # Prometheus 指标定义
```
