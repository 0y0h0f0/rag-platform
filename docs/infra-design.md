# RAG Platform — AI Infra 设计文档

> 本文档详细阐述 RAG Platform 的 AI 基础设施层（`app/infra/`）设计，涵盖 Model Provider 抽象、A/B 测试、分布式追踪、Prometheus 指标、限流、熔断、健康检查、K8s 部署共 8 个核心模块。每个模块包含**设计目标、接口/实现细节、代码片段、面试讨论要点**，适合用于 AI Infra 方向的技术面试展示。

---

## 目录

1. [Model Provider 抽象层设计](#1-model-provider-抽象层设计)
2. [模型 A/B 测试设计](#2-模型-ab-测试设计)
3. [分布式追踪设计 (OpenTelemetry)](#3-分布式追踪设计-opentelemetry)
4. [Prometheus 指标设计](#4-prometheus-指标设计)
5. [限流器设计 (Token Bucket)](#5-限流器设计-token-bucket)
6. [熔断器设计 (Circuit Breaker)](#6-熔断器设计-circuit-breaker)
7. [健康检查设计](#7-健康检查设计)
8. [K8s 部署设计](#8-k8s-部署设计)

---

## 1. Model Provider 抽象层设计

### 1.1 设计目标

| 目标 | 说明 |
|------|------|
| **解耦业务逻辑与模型服务** | `llm_service.py` 只面向 `LLMProvider` 接口编程，完全不感知底层是 Ollama、DeepSeek 还是 OpenAI |
| **热切换 Provider** | 修改环境变量 `LLM_PROVIDER` 即可切换，业务代码零改动 |
| **统一健康检查** | 所有 Provider 实现同一 `health_check() -> bool`，可被 K8s readiness probe 和 Prometheus Gauge 统一消费 |
| **统一指标采集** | 在每个 Provider 的 `chat_completion()` / `embed()` 内嵌入 Prometheus Histogram/Counter，避免指标散落 |

### 1.2 接口设计 (`app/infra/model_provider.py`)

整个抽象层由两个 ABC 和一个数据类组成：

```
┌────────────────────────────────┐
│         LLMResponse            │  ← dataclass
│  content, model, tokens, ...   │
└────────────────────────────────┘
           ▲ 返回
┌────────────────────────────────┐     ┌────────────────────────────────┐
│       LLMProvider (ABC)        │     │   EmbeddingProvider (ABC)      │
│  chat_completion(messages)     │     │   embed(texts) → vectors       │
│  health_check() → bool        │     │   health_check() → bool        │
│  provider_name → str           │     │   provider_name → str          │
│  model_name → str              │     │   model_name → str             │
└────────────────────────────────┘     └────────────────────────────────┘
     ▲           ▲        ▲                    ▲              ▲
     │           │        │                    │              │
  Ollama      API     ABTesting          OllamaEmbed    _LegacyEmbed
 Provider   Provider  Provider            Provider       Provider
```

**LLMResponse 数据类：**

```python
@dataclass
class LLMResponse:
    content: str                          # 模型生成的文本
    model: str                            # 实际使用的模型名称
    prompt_tokens: int = 0                # 输入 token 数
    completion_tokens: int = 0            # 输出 token 数
    total_tokens: int = 0                 # 总 token 数
    metadata: dict = field(default_factory=dict)  # 扩展字段（如 A/B 测试标记）
```

**LLMProvider ABC：**

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
```

**EmbeddingProvider ABC：**

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
```

**设计决策 — 为什么选择 ABC 而不是 Protocol：**

| 比较维度 | ABC | Protocol |
|---------|-----|----------|
| 运行时检查 | `isinstance()` 可用 ✅ | 结构化类型，`isinstance` 需要 `runtime_checkable` |
| 强制实现 | 实例化时即报错 ✅ | 仅在类型检查工具中报错 |
| 本项目需求 | `ProviderRegistry` 中大量使用 `isinstance(llm, ABTestingLLMProvider)` 做分支判断 | 无法满足 |

**设计决策 — 为什么是同步接口而非 async：**

Celery Worker 是同步执行环境（`celery_task_always_eager=true` 时直接在主线程运行），强行 async 需要在 Worker 内 `asyncio.run()`，增加复杂度且无实际收益。FastAPI 端点调用 Provider 时在线程池中执行同步代码（FastAPI 自动处理 `def` 路由的线程调度），性能影响可忽略。

### 1.3 Ollama Provider 实现 (`app/infra/ollama_provider.py`)

#### 核心架构

```
┌──────────────────────────────────────────┐
│             OllamaLLMProvider            │
│                                          │
│  base_url: http://localhost:11434        │
│  model: qwen2.5:7b-instruct-q4_K_M      │
│  timeout: 30s                            │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ POST /api/chat  (非流式)          │  │
│  │ payload = {model, messages,        │  │
│  │            stream: false,          │  │
│  │            options: {temperature,  │  │
│  │                      num_predict}} │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ warmup(): 启动时发送空请求        │  │
│  │ → 触发模型从磁盘加载到 GPU 显存   │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ health_check():                   │  │
│  │ GET /api/tags → 检查模型是否存在   │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│          OllamaEmbeddingProvider         │
│                                          │
│  POST /api/embed                         │
│  payload = {model, input: texts}         │
│  → 返回 embeddings: list[list[float]]    │
└──────────────────────────────────────────┘
```

#### REST API 端点对应

| Ollama API | 方法 | 用途 |
|------------|------|------|
| `/api/chat` | POST | LLM 推理（非流式，`stream: false`） |
| `/api/embed` | POST | 批量文本向量化 |
| `/api/tags` | GET | 列出已加载模型（用于健康检查） |

#### Model Warmup 机制

```python
def warmup(self) -> None:
    try:
        with httpx.Client(timeout=self._timeout, trust_env=False) as client:
            client.post(
                f"{self._base_url}/api/chat",
                json={"model": self._model,
                      "messages": [{"role": "user", "content": "hi"}],
                      "stream": False},
            )
        logger.info("ollama LLM warmup completed for model %s", self._model)
    except Exception:
        logger.warning("ollama LLM warmup failed for model %s", self._model, exc_info=True)
```

**为什么需要 warmup：** Ollama 采用懒加载策略——模型文件在首次请求时才从磁盘（或 HuggingFace 缓存）加载到 GPU 显存。首次加载 7B 模型需要 10-30 秒，如果不做预热，第一个用户请求会超时。在 `ProviderRegistry._init_providers()` 阶段就触发加载，确保服务 ready 后响应时间稳定。

#### 超时与错误处理

```python
# httpx.Client 配置
# trust_env=False: 忽略系统代理设置，避免在容器环境中走代理导致连接超时
with httpx.Client(timeout=self._timeout, trust_env=False) as client:
    resp = client.post(f"{self._base_url}/api/chat", json=payload)
    resp.raise_for_status()  # 4xx/5xx → httpx.HTTPStatusError
```

错误处理链路：`httpx.HTTPError` → 封装为 `RuntimeError` → `LLMService.answer()` 捕获并返回用户友好消息。

#### 指标采集集成

在 `chat_completion()` 中：

```python
start = time.perf_counter()
try:
    # ... HTTP 调用 ...
finally:
    elapsed = time.perf_counter() - start
    MODEL_INFERENCE_LATENCY.labels(
        provider="ollama", model=self._model, operation="chat"
    ).observe(elapsed)

# 响应解析后：
MODEL_INFERENCE_TOKENS.labels(model=self._model, direction="input").inc(prompt_tokens)
MODEL_INFERENCE_TOKENS.labels(model=self._model, direction="output").inc(completion_tokens)
```

`finally` 块确保即使请求失败也记录延迟——这对监控超时和错误分布至关重要。

### 1.4 API Provider 实现 (`app/infra/api_provider.py`)

#### OpenAI 兼容协议

```
POST {base_url}/chat/completions
Headers:
  Authorization: Bearer {api_key}
  Content-Type: application/json

Body:
{
  "model": "deepseek-chat",
  "messages": [...],
  "temperature": 0.2,
  "max_tokens": 512
}

Response:
{
  "choices": [{"message": {"content": "..."}}],
  "usage": {"prompt_tokens": 100, "completion_tokens": 50}
}
```

**一个 Provider 兼容多个后端：** DeepSeek、OpenAI、本地 vLLM、任何 OpenAI-compatible 服务器，只需修改 `LLM_BASE_URL` 和 `LLM_API_KEY`。

#### API Key 动态读取设计

```python
class APILLMProvider(LLMProvider):
    def __init__(self, base_url=None, api_key=None, model=None, timeout=None):
        self._api_key_override = api_key  # None 表示每次从 settings 读取

    @property
    def _api_key(self) -> str:
        return self._api_key_override if self._api_key_override is not None else settings.llm_api_key
```

**为什么用 property 而不是 `__init__` 时缓存：**

1. **测试兼容性**：单元测试中可以通过 monkeypatch 修改 `settings.llm_api_key`，Provider 实例不需要重建
2. **密钥轮换**：如果使用 Vault/K8s Secret 的动态挂载，settings 读取到的值可能更新，property 确保每次调用拿到最新值

#### 健康检查

```python
def health_check(self) -> bool:
    try:
        resp = client.get(f"{self._base_url}/models",
                          headers={"Authorization": f"Bearer {self._api_key}"})
        return resp.status_code == 200
    except Exception:
        return False
```

使用 `/models` 端点（OpenAI 标准端点）做轻量级探活，不消耗推理资源。

### 1.5 Provider Registry (`app/infra/provider_registry.py`)

#### 线程安全单例模式

```python
class ProviderRegistry:
    _instance: ProviderRegistry | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        if cls._instance is None:          # ① 第一次检查（无锁，快速路径）
            with cls._lock:                # ② 获取锁
                if cls._instance is None:  # ③ 第二次检查（持锁，防止并发重复创建）
                    cls._instance = cls()
                    cls._instance._init_providers()
        return cls._instance
```

**双重检查锁定（Double-Checked Locking）的必要性：**

```
Thread A: if None → 获取锁 → if None → 创建实例 → 释放锁
Thread B: if None → 等待锁 → 获取锁 → if not None → 直接返回
Thread C: if not None → 直接返回（不碰锁）
```

FastAPI 使用多线程处理请求（`def` 路由自动在线程池执行），第一批并发请求可能同时到达 `get_instance()`，双重检查保证只初始化一次 Provider。

#### Provider 创建逻辑

```python
def _create_llm_provider(self) -> LLMProvider:
    provider_type = settings.llm_provider  # 读取 LLM_PROVIDER 环境变量

    if provider_type == "ollama":
        return OllamaLLMProvider()
    elif provider_type == "ab_test":
        provider_a = OllamaLLMProvider(model=settings.ab_model_a)
        provider_b = OllamaLLMProvider(model=settings.ab_model_b)
        return ABTestingLLMProvider(provider_a, provider_b, settings.ab_traffic_split)
    else:
        # "api" / "deepseek" / 其他 → OpenAI 兼容 API
        return APILLMProvider()
```

配置驱动的工厂模式——环境变量决定运行时行为：

| `LLM_PROVIDER` | 创建的 Provider | 典型场景 |
|-----------------|----------------|---------|
| `ollama` | `OllamaLLMProvider` | 本地 GPU 推理 |
| `deepseek` / `api` | `APILLMProvider` | 云端 API 调用 |
| `ab_test` | `ABTestingLLMProvider(Ollama, Ollama)` | 模型对比实验 |

#### Legacy Embedding 兼容适配器

```python
class _LegacyEmbeddingProvider(EmbeddingProvider):
    """将旧版 EmbeddingService（sentence-transformers/local hash）适配为新接口。"""
    def __init__(self) -> None:
        from app.services.embedding_service import EmbeddingService
        self._svc = EmbeddingService()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._svc.embed_many(texts)
```

经典**适配器模式**——旧系统的 `EmbeddingService` 接口（`embed_text()` / `embed_many()`）被包装成统一的 `EmbeddingProvider` 接口，实现渐进式迁移而非大规模重写。

#### 自省能力

```python
def list_models(self) -> list[dict]:
    """列出所有已注册的模型信息。"""
    # A/B 测试模式下展开为两个模型条目
    if isinstance(llm, ABTestingLLMProvider):
        models.append({..., "role": "model_a"})
        models.append({..., "role": "model_b"})
    ...

def health_check_all(self) -> dict:
    """对所有 Provider 执行健康检查，返回 {name: bool} 映射。"""
    # A/B 测试模式下分别检查两个子 Provider
```

这些方法被 `/api/v1/infra/models` 和 `/api/v1/infra/models/health` 端点消费，也被 `/health/ready` readiness probe 使用。

### 1.6 面试讨论要点

> **Q: 如果要增加一个新的 Provider（如 Anthropic Claude），需要改多少代码？**
>
> A: 只需 3 步：(1) 新增 `claude_provider.py` 实现 `LLMProvider` ABC；(2) 在 `ProviderRegistry._create_llm_provider()` 增加一个 `elif` 分支；(3) 在 `.env` 中设置 `LLM_PROVIDER=claude`。业务代码（`LLMService`、路由层）零修改。

> **Q: 为什么 `warmup()` 不放在 ABC 中作为必须实现的方法？**
>
> A: 并非所有 Provider 需要预热（API Provider 无需预热），将其作为可选方法避免强制空实现。目前由具体 Provider 暴露，Registry 可以在需要时调用。

---

## 2. 模型 A/B 测试设计

### 2.1 ABTestingLLMProvider

#### 架构图

```
                   ┌─────────────────────────────────┐
                   │     ABTestingLLMProvider         │
    request ──────▶│                                  │
                   │  random() < split(0.8)?          │
                   │       │              │           │
                   │      YES            NO           │
                   │       ▼              ▼           │
                   │  ProviderA      ProviderB        │
                   │  (qwen2.5:7b)  (qwen2.5:3b)     │
                   │       │              │           │
                   │       ▼              ▼           │
                   │   LLMResponse + metadata         │
                   │   {ab_model: "qwen2.5:7b"}       │
                   │                                  │
                   │  ┌─── ABStats ──────────────┐    │
                   │  │ per-model:               │    │
                   │  │   requests, latency,     │    │
                   │  │   tokens                 │    │
                   │  │ thread-safe (Lock)       │    │
                   │  └──────────────────────────┘    │
                   └─────────────────────────────────┘
```

#### 核心实现

```python
class ABTestingLLMProvider(LLMProvider):
    def __init__(self, provider_a: LLMProvider, provider_b: LLMProvider, split: float = 0.8):
        self._provider_a = provider_a
        self._provider_b = provider_b
        self._split = split                            # A 的流量比例
        self._lock = threading.Lock()
        self._stats: dict[str, ABStats] = {
            provider_a.model_name: ABStats(),
            provider_b.model_name: ABStats(),
        }

    def _pick_provider(self) -> LLMProvider:
        return self._provider_a if random.random() < self._split else self._provider_b

    def chat_completion(self, messages, **kwargs) -> LLMResponse:
        provider = self._pick_provider()
        start = time.perf_counter()
        response = provider.chat_completion(messages, **kwargs)
        elapsed = time.perf_counter() - start

        with self._lock:                               # 线程安全更新统计
            stats = self._stats.setdefault(provider.model_name, ABStats())
            stats.requests += 1
            stats.total_latency += elapsed
            stats.total_tokens += response.total_tokens

        response.metadata["ab_model"] = provider.model_name   # 注入模型标识
        return response
```

**关键设计点：**

1. **装饰器模式**：`ABTestingLLMProvider` 本身也是 `LLMProvider`，对上层透明
2. **metadata 注入**：通过 `response.metadata["ab_model"]` 传递模型版本信息，`LLMService.answer_with_metadata()` 可以把它返回给前端
3. **无侵入**：业务代码 `registry.get_llm().chat_completion(messages)` 不需要知道底层是否在做 A/B 测试

### 2.2 Stats Collection

```python
@dataclass
class ABStats:
    requests: int = 0
    total_latency: float = 0.0
    total_tokens: int = 0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.requests if self.requests else 0.0

    @property
    def avg_tokens(self) -> float:
        return self.total_tokens / self.requests if self.requests else 0.0
```

统计维度：

| 指标 | 计算方式 | 用途 |
|------|---------|------|
| `requests` | 累加 | 样本量，用于判断统计显著性 |
| `avg_latency` | `total_latency / requests` | 延迟对比，判断大模型 vs 小模型的速度差异 |
| `avg_tokens` | `total_tokens / requests` | Token 消耗对比，评估成本差异 |

**线程安全**：使用 `threading.Lock()` 保护统计更新。虽然 Python GIL 在 CPython 下保证了基本的原子性，但 `stats.requests += 1` 并非单个字节码操作（涉及 LOAD_ATTR + BINARY_ADD + STORE_ATTR），在多线程场景下可能出现竞争条件。

### 2.3 Dynamic Configuration

```
POST /api/v1/infra/ab/config
{
    "traffic_split": 0.5
}

Response:
{
    "traffic_split": 0.5,
    "model_a": "qwen2.5:7b",
    "model_b": "qwen2.5:3b"
}
```

实现：

```python
@router.post("/ab/config", response_model=ABConfigResponse)
def update_ab_config(payload: ABConfigRequest, registry=Depends(get_provider_registry)):
    llm = registry.get_llm()
    if not isinstance(llm, ABTestingLLMProvider):
        return ABConfigResponse(traffic_split=1.0, model_a="N/A", model_b="N/A")
    llm.split = payload.traffic_split       # 运行时调整，无需重启
    return ABConfigResponse(...)
```

`split` 的 setter 做了边界保护：

```python
@split.setter
def split(self, value: float) -> None:
    self._split = max(0.0, min(1.0, value))  # 钳制到 [0.0, 1.0]
```

### 2.4 面试讨论要点

> **Q: 为什么使用随机分流而不是 Round-Robin？**
>
> A: 随机分流的统计性质更优。Round-Robin 在流量存在周期性模式（如早高峰）时，两个模型可能系统性地处理不同类型的请求（奇数请求全是简单查询，偶数请求全是复杂查询），导致对比偏倚。随机分流确保在大样本下两组请求分布一致，满足 A/B 测试的**独立性**假设。

> **Q: 如何扩展为 Multi-Armed Bandit？**
>
> A: 将固定 `split` 替换为 Thompson Sampling 或 UCB 算法：(1) 为每个模型维护一个 Beta 分布（基于成功/失败反馈）；(2) 每次请求时从各模型的分布中采样，选择采样值最高的模型；(3) 根据用户反馈（如 thumbs up/down）更新分布参数。这样系统会自动收敛到更优的模型，同时保持一定的探索。

> **Q: 为什么 in-memory stats 就够了？**
>
> A: 当前是单进程（一个 uvicorn worker），内存中的统计就是全局视图。如果扩展到多 worker/多 Pod，需要改为 Redis 存储统计（`HINCRBY` 原子操作），或直接从 Prometheus 的 `rag_model_inference_seconds` histogram 聚合。但 MVP 阶段内存方案足够，YAGNI 原则。

---

## 3. 分布式追踪设计 (OpenTelemetry)

### 3.1 Architecture

```
┌──────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  FastAPI App  │────▶│  TracerProvider       │────▶│   Jaeger    │
│              │     │  ├─ Resource           │     │  (UI:16686) │
│  trace_span()│     │  │  service.name=      │     │  (OTLP:4317)│
│  context mgr │     │  │  "rag-platform"     │     └─────────────┘
│              │     │  ├─ BatchSpanProcessor  │
│  FastAPI     │     │  │  (异步批量导出)       │
│  Instrumentor│     │  └─ OTLPSpanExporter   │
└──────────────┘     │     endpoint=4317      │
                     │     protocol=gRPC      │
       ┌─────────┐  └──────────────────────┘
       │ Celery   │        ▲
       │ Worker   │────────┘
       │ (trace   │   inject/extract
       │  context │   propagation
       │  propagation)
       └─────────┘
```

#### 初始化流程 (`init_tracing()`)

```python
def init_tracing() -> None:
    if not settings.otel_enabled:         # OTEL_ENABLED=false 时完全跳过
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_endpoint,  # http://jaeger:4317
        insecure=True                               # 内网环境，无需 TLS
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(settings.otel_service_name)
```

**零开销降级：** 当 `OTEL_ENABLED=false` 时，`get_tracer()` 返回 `_NoOpTracer`，所有 `trace_span()` 调用退化为空上下文管理器，无任何性能开销。

### 3.2 Span Hierarchy

完整的请求链路追踪层级：

```
HTTP POST /api/v1/chat                              ← FastAPIInstrumentor 自动创建
  └── retrieval.search                              ← retrieval_service 手动创建
      │   attributes: search_mode=hybrid, top_k=5
      ├── vector_search                             ← 向量检索子 span
      │   └── embedding.embed                       ← Embedding 子 span
      │       attributes: model=nomic-embed-text,
      │                   batch_size=1
      └── bm25_search                               ← BM25 检索子 span
          attributes: num_results=5
  └── llm.chat_completion                           ← LLM 推理 span
      attributes: model=qwen2.5:7b,
                  prompt_tokens=340,
                  completion_tokens=128,
                  total_tokens=468
```

每个 span 记录的关键属性：

| Span | Attributes | 调试价值 |
|------|-----------|---------|
| `retrieval.search` | `search_mode`, `top_k`, `cache_hit` | 快速定位检索策略和缓存命中 |
| `embedding.embed` | `model`, `batch_size` | 分析嵌入批量大小是否合理 |
| `llm.chat_completion` | `model`, `*_tokens` | 定位慢查询的瓶颈是模型推理还是检索 |

### 3.3 `trace_span()` Helper

```python
@contextmanager
def trace_span(name: str, attributes: dict | None = None) -> Generator:
    """上下文管理器，创建一个 trace span。追踪禁用时为 no-op。"""
    tracer = get_tracer()
    if isinstance(tracer, _NoOpTracer):
        yield _NoOpSpan()           # 零开销
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span
```

**使用方式：**

```python
with trace_span("llm.chat_completion", {"model": self._model}) as span:
    response = self._call_ollama(messages)
    span.set_attribute("tokens", response.total_tokens)
```

**NoOp 实现：**

```python
class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield _NoOpSpan()

class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass
    def set_status(self, *args, **kwargs) -> None:
        pass
    def record_exception(self, *args, **kwargs) -> None:
        pass
```

### 3.4 Celery Trace Propagation

跨进程追踪传播——API 进程创建的 trace 需要在 Celery Worker 中延续：

```
┌─────────────┐    task headers    ┌──────────────┐
│  API Server  │──────────────────▶│ Celery Worker │
│              │  {"traceparent":  │              │
│ inject_trace │   "00-abc..."}   │ extract_trace │
│ _context()   │                  │ _context()    │
└─────────────┘                   └──────────────┘
```

**注入（API 端）：**

```python
def inject_trace_context() -> dict:
    """提取当前 trace context 放入 dict，传递给 Celery task headers。"""
    if not settings.otel_enabled:
        return {}
    carrier: dict[str, str] = {}
    inject(carrier)     # W3C TraceContext 格式: traceparent, tracestate
    return carrier
```

**提取（Worker 端）：**

```python
def extract_trace_context(carrier: dict) -> Any:
    """从 carrier dict 恢复 trace context。"""
    if not settings.otel_enabled or not carrier:
        return None
    return extract(carrier)   # 恢复 parent span context
```

**使用方式（在 Celery task 中）：**

```python
@celery_app.task
def ingest_task(doc_id: str, trace_ctx: dict = None):
    ctx = extract_trace_context(trace_ctx or {})
    with trace_span("celery.ingest_task", {"doc_id": doc_id}):
        # ... 任务逻辑 ...
```

### 3.5 FastAPI 自动 Instrumentation

```python
def instrument_fastapi(app: Any) -> None:
    if not settings.otel_enabled:
        return
    FastAPIInstrumentor.instrument_app(app)
```

`FastAPIInstrumentor` 自动为每个 HTTP 请求创建 root span，包含：
- `http.method` (GET/POST)
- `http.url`
- `http.status_code`
- `http.request.duration`

### 3.6 面试讨论要点

> **Q: 为什么选择 OTLP gRPC 而不是 HTTP 协议？**
>
> A: (1) **性能**：gRPC 使用 HTTP/2 多路复用和 protobuf 二进制编码，比 JSON over HTTP 体积小 ~60%，解析速度快 ~10x；(2) **流式传输**：gRPC 支持双向流，BatchSpanProcessor 可以在单个连接上持续发送 span 批次；(3) **生态标准**：Jaeger、Tempo、Datadog 原生支持 OTLP gRPC，HTTP 仅为兼容备选。

> **Q: 为什么使用 BatchSpanProcessor 而不是 SimpleSpanProcessor？**
>
> A: `SimpleSpanProcessor` 在每个 span 结束时同步导出，直接增加请求延迟。`BatchSpanProcessor` 将 span 缓存到内存队列，由后台线程批量导出（默认 5 秒或 512 个 span），对请求延迟的影响趋近于零。trade-off 是进程崩溃时可能丢失未导出的 span，但追踪数据本身是可降级的，不影响业务正确性。

> **Q: NoOp 模式的价值是什么？**
>
> A: 开发和测试环境通常不需要追踪，`_NoOpTracer` / `_NoOpSpan` 确保：(1) 不需要安装 opentelemetry SDK 也能运行（`ImportError` 被捕获）；(2) 代码中的 `trace_span()` 调用不需要 if-else 判断，保持代码整洁；(3) 零性能开销——空方法调用的成本可忽略不计。

---

## 4. Prometheus 指标设计

### 4.1 指标总览

所有指标定义在 `app/core/metrics.py`，通过 `/metrics` 端点以 Prometheus 文本格式暴露。

#### 原有业务指标

| 指标名 | 类型 | 用途 |
|--------|------|------|
| `rag_platform_document_upload_total` | Counter | 文档上传总量 |
| `rag_platform_deduplicated_upload_total` | Counter | 去重跳过的上传次数 |
| `rag_platform_search_requests_total` | Counter | 搜索请求总量 |
| `rag_platform_search_latency_seconds` | Histogram | 搜索延迟分布 |
| `rag_platform_search_cache_hit_total` | Counter | 缓存命中次数 |
| `rag_platform_search_cache_miss_total` | Counter | 缓存未命中次数 |
| `rag_platform_ingestion_tasks_total` | Counter (by status) | 数据摄入任务计数 |

#### 新增 AI Infra 指标

| 指标名 | 类型 | Labels | 用途 |
|--------|------|--------|------|
| `rag_model_inference_seconds` | Histogram | `provider`, `model`, `operation` | 模型推理延迟分布（P50/P95/P99） |
| `rag_model_tokens_total` | Counter | `model`, `direction` (input/output) | Token 吞吐量监控，成本核算 |
| `rag_model_health_status` | Gauge | `provider`, `model` | 模型服务健康状态 (1/0) |
| `rag_rate_limit_rejected_total` | Counter | - | 被限流拒绝的请求数 |
| `rag_embedding_batch_size` | Histogram | - | Embedding 批处理大小分布 |

### 4.2 指标定义代码

```python
# --- Model inference metrics ---

MODEL_INFERENCE_LATENCY = Histogram(
    "rag_model_inference_seconds",
    "Model inference latency",
    labelnames=("provider", "model", "operation"),   # operation: chat / embed
)

MODEL_INFERENCE_TOKENS = Counter(
    "rag_model_tokens_total",
    "Total tokens processed",
    labelnames=("model", "direction"),               # direction: input / output
)

MODEL_HEALTH_STATUS = Gauge(
    "rag_model_health_status",
    "Model service health (1=healthy, 0=unhealthy)",
    labelnames=("provider", "model"),
)

# --- Rate limiting metrics ---

RATE_LIMIT_REJECTED = Counter(
    "rag_rate_limit_rejected_total",
    "Requests rejected by rate limiter",
)

# --- Embedding batch metrics ---

EMBEDDING_BATCH_SIZE = Histogram(
    "rag_embedding_batch_size",
    "Embedding batch sizes",
)
```

### 4.3 指标采集点

```
┌─────────────────────────────────────────────────────────────────┐
│                    指标采集点分布图                                │
│                                                                  │
│  ollama_provider.py                                              │
│    chat_completion()                                             │
│      ├── MODEL_INFERENCE_LATENCY.observe(elapsed)    [finally]   │
│      ├── MODEL_INFERENCE_TOKENS.inc(prompt_tokens)   [input]     │
│      └── MODEL_INFERENCE_TOKENS.inc(completion_tokens)[output]   │
│    embed()                                                       │
│      ├── EMBEDDING_BATCH_SIZE.observe(len(texts))                │
│      └── MODEL_INFERENCE_LATENCY.observe(elapsed)    [finally]   │
│                                                                  │
│  api_provider.py                                                 │
│    chat_completion()                                             │
│      ├── MODEL_INFERENCE_LATENCY.observe(elapsed)    [finally]   │
│      ├── MODEL_INFERENCE_TOKENS.inc(prompt_tokens)               │
│      └── MODEL_INFERENCE_TOKENS.inc(completion_tokens)           │
│                                                                  │
│  rate_limiter.py                                                 │
│    dispatch()                                                    │
│      └── RATE_LIMIT_REJECTED.inc()   [when bucket empty]         │
│                                                                  │
│  routes_infra.py                                                 │
│    models_health()                                               │
│      └── MODEL_HEALTH_STATUS.set(1.0 / 0.0)  [per provider]     │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 Grafana Dashboard 查询示例

**模型推理延迟 P95：**

```promql
histogram_quantile(0.95,
  rate(rag_model_inference_seconds_bucket{operation="chat"}[5m])
)
```

**每分钟 Token 吞吐量：**

```promql
sum(rate(rag_model_tokens_total[5m])) by (model, direction) * 60
```

**缓存命中率：**

```promql
rate(rag_platform_search_cache_hit_total[5m])
/
(rate(rag_platform_search_cache_hit_total[5m]) + rate(rag_platform_search_cache_miss_total[5m]))
```

**限流拒绝率：**

```promql
rate(rag_rate_limit_rejected_total[5m])
```

### 4.5 面试讨论要点

> **Q: 为什么推理延迟用 Histogram 而不是 Summary？**
>
> A: Histogram 可以跨多个实例聚合（`histogram_quantile` 在服务端计算），Summary 的分位数在客户端预计算，无法跨实例聚合。在多 Pod 部署下，需要全局 P95 而非单个 Pod 的 P95。

> **Q: 为什么 `MODEL_INFERENCE_LATENCY.observe()` 放在 `finally` 块？**
>
> A: 确保即使请求失败（超时、5xx）也记录延迟。这些失败请求的延迟对排障至关重要——如果只记录成功请求，P99 会看起来很好，但实际用户体验很差（超时请求被隐藏了）。

> **Q: Label 基数爆炸的风险？**
>
> A: `model` label 的取值有限（2-3 个模型），`operation` 只有 `chat`/`embed`，`direction` 只有 `input`/`output`，`provider` 只有 `ollama`/`api`。总组合 < 20，不会触发 Prometheus 的高基数问题。如果引入 per-user 维度则需要用日志而非指标。

---

## 5. 限流器设计 (Token Bucket)

### 5.1 Token Bucket 算法

```
┌────────────────────────────────────────────────┐
│                 Token Bucket                    │
│                                                 │
│  capacity = RPM (30)   ← 桶的最大容量（突发上限）│
│  rate = RPM/60 (0.5)   ← 每秒补充的 token 数    │
│  tokens = [当前余量]                             │
│                                                 │
│  ┌─────────────────────────────────────┐        │
│  │  每秒补充 0.5 个 token              │        │
│  │  ████████████████░░░░░░░░░░░░░░░░   │        │
│  │  ← 当前 tokens    空闲容量 →         │        │
│  └─────────────────────────────────────┘        │
│                                                 │
│  acquire():                                     │
│    tokens >= 1 → 消耗 1 token, 返回 True        │
│    tokens < 1  → 返回 False (拒绝)              │
└────────────────────────────────────────────────┘
```

**算法流程：**

1. 每次调用 `acquire()` 时，先根据时间差补充 token：`tokens += elapsed * rate`
2. tokens 上限为 capacity（不会无限累积）
3. 如果 `tokens >= 1.0`，扣减 1 个 token 并放行
4. 否则拒绝请求

**与固定窗口对比：** Token Bucket 天然支持突发流量——如果前 30 秒无请求，桶满为 30 个 token，可以瞬间处理 30 个并发请求；固定窗口在窗口边界处可能出现 2x 突发（前一窗口末尾 + 后一窗口开头）。

### 5.2 实现细节

```python
class TokenBucket:
    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate              # tokens per second
        self._capacity = capacity      # max burst
        self._tokens = capacity        # 启动时桶满
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            # 懒惰补充：不用定时器，在每次请求时计算应补充的 token 数
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
```

**为什么用 `time.monotonic()` 而不是 `time.time()`：**

`time.time()` 受 NTP 时钟调整影响，可能回拨导致 `elapsed` 为负数，进而从桶中扣减 token。`time.monotonic()` 单调递增，不受系统时钟影响。

#### FastAPI Middleware 集成

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rpm: int | None = None) -> None:
        super().__init__(app)
        rpm = rpm or settings.rate_limit_requests_per_minute    # 默认 30 RPM
        self._bucket = TokenBucket(rate=rpm / 60.0, capacity=rpm)

    async def dispatch(self, request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # 豁免路径：健康检查和指标端点不受限流
        if request.url.path in ("/health", "/health/ready", "/metrics"):
            return await call_next(request)

        if not self._bucket.acquire():
            RATE_LIMIT_REJECTED.inc()       # Prometheus 指标
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
            )

        return await call_next(request)
```

**豁免路径设计：** `/health`、`/health/ready`、`/metrics` 是基础设施端点，被 K8s probe 和 Prometheus scraper 高频调用，不应受业务限流影响。如果限流了 `/health/ready`，K8s 会误判 Pod 不健康。

#### 注册到 FastAPI

```python
# app/main.py
from app.infra.rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)
```

### 5.3 面试讨论要点

> **Q: Token Bucket vs Sliding Window vs Leaky Bucket 对比？**
>
> | 算法 | 突发处理 | 实现复杂度 | 内存开销 | 适用场景 |
> |------|---------|-----------|---------|---------|
> | Token Bucket | 允许突发（up to capacity） | 低 | O(1) | 通用 API 限流 |
> | Sliding Window | 精确控制窗口内总量 | 中 | O(N) per window | 严格 QPS 控制 |
> | Leaky Bucket | 平滑输出速率 | 低 | O(1) | 流量整形 |
>
> 本项目选择 Token Bucket：实现简单，允许合理突发（用户短时间发多个请求是合理的），内存开销 O(1)。

> **Q: 为什么是 in-memory 而不用 Redis？**
>
> A: 当前单进程部署，内存限流即可。多 Pod 场景下的选择：
> - **Redis + Lua Script**：`MULTI/EXEC` 保证原子性，适合精确限流
> - **每个 Pod 独立限流**：总限额 = 单 Pod 限额 * Pod 数，简单但不精确
> - **Rate Limiting Gateway**：在 Nginx/Envoy 层限流，不需要应用代码参与
>
> 推荐先用 Pod 独立限流（因为 HPA 会动态调整 Pod 数，总容量自然伸缩），不够精确时再上 Redis。

> **Q: 如何扩展为 per-user / per-API-key 限流？**
>
> A: 将单个 `TokenBucket` 改为 `dict[str, TokenBucket]`，key 为 user_id 或 API key。需要额外处理：(1) 过期桶的清理（LRU 淘汰或定时清理）；(2) 内存上限（限制最大桶数量）；(3) 分布式场景下改用 Redis + Lua。

---

## 6. 熔断器设计 (Circuit Breaker)

### 6.1 三状态转换

```
               success_threshold 次成功
    ┌──────────────────────────────────────────┐
    │                                          │
    ▼                                          │
┌────────┐   failure_threshold 次    ┌────────┐│   recovery_timeout   ┌───────────┐
│ CLOSED  │──── 连续失败 ──────────▶│  OPEN   ││◀──── 秒后 ─────────│ HALF_OPEN  │
│         │                         │         │└─────────────────────▶│           │
│ 正常放行 │                         │ 快速失败 │                      │ 试探放行   │
│         │◀──── 成功 ──────────────│         │                      │           │
└────────┘                         └────────┘        失败 ──────────▶│           │
    ▲                                                                └───────────┘
    │                                                                      │
    └──────────────────────── 成功 ────────────────────────────────────────┘
```

**三状态模型的直觉解释：**

| 状态 | 类比 | 行为 |
|------|------|------|
| CLOSED | 电路闭合，电流通过 | 正常转发请求到后端服务 |
| OPEN | 电路断开，电流中断 | 立即返回错误，不尝试调用后端（保护已崩溃的服务） |
| HALF_OPEN | 试探性接通 | 允许少量请求通过，测试后端是否恢复 |

### 6.2 配置参数

```python
class CircuitBreaker:
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,        # 连续失败 5 次后开路
        recovery_timeout: float = 30.0,    # 开路 30 秒后进入半开
        half_open_max_calls: int = 1,      # 半开状态最多放行 1 个请求
    ):
```

| 参数 | 默认值 | 调优建议 |
|------|-------|---------|
| `failure_threshold` | 5 | 模型推理服务偶尔超时是正常的，设太低（如 2）会频繁触发；太高（如 20）则保护不及时 |
| `recovery_timeout` | 30s | 与 Ollama 模型重新加载时间匹配；GPU OOM 恢复可能需要更长时间 |
| `half_open_max_calls` | 1 | 设为 1 防止雪崩——如果半开状态放行太多请求到刚恢复的服务，可能再次压垮它 |

### 6.3 实现细节

#### 状态检查（惰性转换）

```python
@property
def state(self) -> CircuitState:
    with self._lock:
        if self._state == CircuitState.OPEN:
            # 检查是否到了尝试恢复的时间
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("circuit breaker '%s' transitioning to HALF_OPEN", self.name)
        return self._state
```

**惰性转换**：不使用定时器，而是在每次访问 `state` 时检查时间。优点：无后台线程开销；缺点：如果一直没有请求，状态不会自动转换（但这也没关系——没有请求就不需要转换）。

#### `call()` 方法

```python
def call(self, func: Callable[..., T], *args, **kwargs) -> T:
    current_state = self.state

    if current_state == CircuitState.OPEN:
        raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' is OPEN")

    if current_state == CircuitState.HALF_OPEN:
        with self._lock:
            if self._half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerOpen(f"HALF_OPEN limit reached")
            self._half_open_calls += 1

    try:
        result = func(*args, **kwargs)
        self._on_success()
        return result
    except Exception:
        self._on_failure()
        raise
```

**调用方使用方式：**

```python
breaker = CircuitBreaker(name="ollama-llm", failure_threshold=5, recovery_timeout=30.0)

try:
    response = breaker.call(provider.chat_completion, messages)
except CircuitBreakerOpen:
    # Fallback: 使用缓存结果或返回降级响应
    return "模型服务暂时不可用，请稍后重试。"
except RuntimeError:
    # 模型调用本身失败（已被 breaker 记录）
    return "模型调用失败。"
```

#### 成功/失败处理

```python
def _on_success(self) -> None:
    with self._lock:
        if self._state == CircuitState.HALF_OPEN:
            logger.info("circuit breaker '%s' recovered, transitioning to CLOSED", self.name)
        self._state = CircuitState.CLOSED
        self._failure_count = 0

def _on_failure(self) -> None:
    with self._lock:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN            # 半开失败 → 直接开路
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN            # 连续失败超过阈值 → 开路
```

### 6.4 面试讨论要点

> **Q: 为什么是三状态而不是两状态（CLOSED/OPEN）？**
>
> A: 没有 HALF_OPEN，系统面临两难：
> - `recovery_timeout` 后直接回到 CLOSED → 如果后端还没恢复，大量请求涌入再次压垮它
> - `recovery_timeout` 后继续 OPEN → 后端恢复了也永远无法自愈
>
> HALF_OPEN 的价值在于**可控的探测**：只放 1 个请求去测试，成功则恢复流量，失败则继续保护。

> **Q: HALF_OPEN 如何防止雷群效应（Thundering Herd）？**
>
> A: `half_open_max_calls = 1`——在探测阶段只允许 1 个请求通过，其余请求继续快速失败。如果这 1 个请求成功，状态转为 CLOSED，后续请求正常通过；如果失败，回到 OPEN，等待下一轮 recovery_timeout。

> **Q: 与重试模式的关系？**
>
> A: 重试和熔断是互补的：
> - **重试**：处理瞬时故障（网络抖动、偶发超时），通常重试 2-3 次
> - **熔断**：处理持续故障（服务宕机、GPU OOM），避免重试风暴
>
> 组合使用：先重试 N 次 → 重试全部失败计为 1 次熔断失败 → 连续多次全部失败后开路。

> **Q: 如何与 Provider 集成？**
>
> A: 当前 `CircuitBreaker` 作为独立组件提供。可以在 `ProviderRegistry` 中为每个 Provider 创建一个 breaker：
> ```python
> self._llm_breaker = CircuitBreaker(name=f"llm-{provider.provider_name}")
> ```
> 在 `get_llm().chat_completion()` 调用时包装：
> ```python
> return self._llm_breaker.call(self._llm_provider.chat_completion, messages)
> ```

---

## 7. 健康检查设计

### 7.1 双层健康检查

```
┌─────────────────────────────────────────────────────────┐
│                  K8s 健康检查机制                         │
│                                                          │
│  /health (Liveness Probe)                                │
│  ├── 检查内容: 进程存活                                    │
│  ├── 失败后果: K8s 重启 Pod                               │
│  ├── 检查频率: 每 15 秒                                   │
│  └── 实现: return {"status": "ok"}                       │
│                                                          │
│  /health/ready (Readiness Probe)                         │
│  ├── 检查内容: 所有依赖服务                                │
│  │   ├── Database: SELECT 1                              │
│  │   ├── Redis: PING                                     │
│  │   └── Models: ProviderRegistry.health_check_all()     │
│  ├── 失败后果: Pod 从 Service endpoints 移除（不接收流量） │
│  ├── 检查频率: 每 10 秒                                   │
│  └── 实现: 返回 200 (全部健康) 或 503 (有组件不健康)       │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Liveness Probe 实现

```python
@app.get("/health")
def health() -> dict[str, str]:
    """Shallow liveness probe for K8s."""
    return {"status": "ok"}
```

**设计原则**：Liveness 必须极其轻量——只判断进程是否存活。如果在 liveness 中检查数据库，而数据库暂时不可用，K8s 会重启 Pod；但 Pod 重启也连不上数据库，进入无限重启循环（CrashLoopBackOff）。

### 7.3 Readiness Probe 实现

```python
@app.get("/health/ready")
def health_ready() -> dict:
    """Deep readiness probe: checks DB, Redis, and model services."""
    checks: dict[str, bool] = {}

    # Database check
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Redis check
    try:
        r = get_redis()
        if r is not None:
            r.ping()
            checks["redis"] = True
        else:
            checks["redis"] = False
    except Exception:
        checks["redis"] = False

    # Model service checks
    try:
        registry = ProviderRegistry.get_instance()
        model_health = registry.health_check_all()
        checks.update(model_health)      # 如 {"llm/qwen2.5:7b": True, "embedding/nomic-embed-text": True}
    except Exception:
        checks["models"] = False

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503
    return JSONResponse(
        content={"status": "ready" if all_healthy else "not_ready", "checks": checks},
        status_code=status_code,
    )
```

**响应示例：**

健康：
```json
{
    "status": "ready",
    "checks": {
        "database": true,
        "redis": true,
        "llm/qwen2.5:7b": true,
        "embedding/nomic-embed-text": true
    }
}
```

部分不健康（返回 503）：
```json
{
    "status": "not_ready",
    "checks": {
        "database": true,
        "redis": true,
        "llm/qwen2.5:7b": false,
        "embedding/nomic-embed-text": true
    }
}
```

### 7.4 K8s Probe 配置

```yaml
# k8s/api-deployment.yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  periodSeconds: 10          # 每 10 秒检查
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  periodSeconds: 15          # 每 15 秒检查
```

#### 完整 Probe 决策流

```
Pod 启动
  │
  ▼
Liveness Probe (/health) ── 失败 ──▶ 重启 Pod
  │ 成功
  ▼
Readiness Probe (/health/ready) ── 失败 ──▶ 从 Service 移除（不接收流量）
  │ 成功                                       │
  ▼                                            │
加入 Service endpoints                   持续检查直到恢复
  │                                            │
接收流量 ◀─────────────────────────────────────┘
```

### 7.5 面试讨论要点

> **Q: 为什么分离 Liveness 和 Readiness？**
>
> A: 解决不同层面的问题：
> - **Liveness 失败** → 进程卡死（死锁、内存泄漏）→ 需要重启
> - **Readiness 失败** → 依赖不可用（DB 宕机、模型未加载）→ 暂停接收流量
>
> 如果混在一起：DB 临时不可用 → Liveness 失败 → Pod 重启 → 重启后 DB 仍不可用 → 再次重启 → CrashLoopBackOff。分离后：DB 不可用 → Readiness 失败 → 停止接收流量 → DB 恢复 → Readiness 通过 → 恢复流量。Pod 始终存活，避免无意义重启。

> **Q: Readiness 失败时会发生什么？**
>
> A: K8s 从该 Pod 所属 Service 的 endpoints 列表中移除该 Pod。负载均衡器（kube-proxy / Envoy）不再将新请求路由到该 Pod。已在处理的请求不受影响（graceful）。Readiness 恢复后自动重新加入。

> **Q: 如何为模型加载添加 Startup Probe？**
>
> A: 大模型加载可能需要 30-120 秒，超过 liveness probe 的默认超时。添加 Startup Probe：
> ```yaml
> startupProbe:
>   httpGet:
>     path: /health/ready
>     port: 8000
>   failureThreshold: 30      # 最多等 30 * 10 = 300 秒
>   periodSeconds: 10
> ```
> Startup Probe 成功前，Liveness 和 Readiness 不启动，避免因模型加载慢而被误杀。

---

## 8. K8s 部署设计

### 8.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Namespace: rag-platform                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   API Server  │  │   API Server  │  │      Ollama          │   │
│  │   (Deployment)│  │   (Deployment)│  │    (StatefulSet)     │   │
│  │   Pod 1       │  │   Pod 2       │  │    Pod 1 (GPU)       │   │
│  │   cpu: 250m-1 │  │   cpu: 250m-1 │  │    nvidia.com/gpu: 1 │   │
│  │   mem: 512M-1G│  │   mem: 512M-1G│  │    storage: 20Gi     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                  │                      │               │
│         ▼                  ▼                      ▼               │
│  ┌──────────────────────────────┐    ┌──────────────────────┐   │
│  │     Service: api             │    │  Service: ollama      │   │
│  │     :8000                    │    │  :11434               │   │
│  └──────────────────────────────┘    └──────────────────────┘   │
│         │                                                        │
│  ┌──────┴──────────────────────────────────────────────┐        │
│  │                  HPA: api-hpa                        │        │
│  │   min=2, max=5, cpu target=70%                       │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │  Celery Worker│  │  Celery Worker│                             │
│  │  (Deployment) │  │  (Deployment) │                             │
│  │  Pod 1        │  │  Pod 2        │                             │
│  └──────┬───────┘  └──────┬───────┘                             │
│         │                  │                                     │
│  ┌──────┴──────────────────────────────────────────────┐        │
│  │                  HPA: worker-hpa                     │        │
│  │   min=2, max=5, cpu target=70%                       │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  PostgreSQL   │  │    Redis     │  │    Jaeger    │          │
│  │  (Deployment) │  │ (Deployment) │  │ (Deployment) │          │
│  │  PVC: 10Gi    │  │              │  │  UI: 16686   │          │
│  └──────────────┘  └──────────────┘  │  OTLP: 4317  │          │
│                                       └──────────────┘          │
│  ┌──────────────────┐  ┌────────────────────┐                   │
│  │   ConfigMap       │  │    Secret           │                   │
│  │  rag-platform-    │  │  rag-platform-      │                   │
│  │  config           │  │  secret             │                   │
│  │  (所有非敏感配置)  │  │  (LLM_API_KEY)      │                   │
│  └──────────────────┘  └────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 资源清单

#### Namespace 隔离

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rag-platform
  labels:
    app: rag-platform
```

所有资源在 `rag-platform` 命名空间下，与集群其他服务隔离。可以对命名空间设置 ResourceQuota 限制总资源用量。

#### ConfigMap (非敏感配置)

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rag-platform-config
  namespace: rag-platform
data:
  DATABASE_URL: "postgresql://postgres:postgres@postgres:5432/rag_platform"
  REDIS_URL: "redis://redis:6379/0"
  CELERY_BROKER_URL: "redis://redis:6379/1"
  CELERY_RESULT_BACKEND: "redis://redis:6379/2"
  CELERY_TASK_ALWAYS_EAGER: "false"          # 生产环境使用真正的 Celery worker
  LLM_PROVIDER: "ollama"
  EMBEDDING_PROVIDER: "ollama"
  OLLAMA_BASE_URL: "http://ollama:11434"     # K8s Service DNS
  OLLAMA_LLM_MODEL: "qwen2.5:7b-instruct-q4_K_M"
  OLLAMA_EMBED_MODEL: "nomic-embed-text"
  OTEL_ENABLED: "true"
  OTEL_EXPORTER_ENDPOINT: "http://jaeger:4317"
  RATE_LIMIT_ENABLED: "true"
  RATE_LIMIT_REQUESTS_PER_MINUTE: "30"
  # ... 其他配置 ...
```

#### Secret (敏感信息)

```yaml
# k8s/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-platform-secret
  namespace: rag-platform
type: Opaque
data:
  LLM_API_KEY: Y2hhbmdlbWU=     # base64 编码，生产环境应使用 Sealed Secrets 或 Vault
```

**配置注入方式：**

```yaml
# api-deployment.yaml 中的 Pod spec
envFrom:
  - configMapRef:
      name: rag-platform-config    # 所有 ConfigMap 键值注入为环境变量
  - secretRef:
      name: rag-platform-secret    # Secret 键值注入为环境变量
```

`pydantic-settings` 自动从环境变量读取配置，实现了 K8s ConfigMap/Secret → Python Settings 的无缝桥接。

### 8.3 GPU 调度 (Ollama StatefulSet)

```yaml
# k8s/ollama-deployment.yaml
apiVersion: apps/v1
kind: StatefulSet                   # ← 不是 Deployment
metadata:
  name: ollama
spec:
  serviceName: ollama
  replicas: 1                       # GPU 资源昂贵，通常只部署 1 个副本
  template:
    spec:
      nodeSelector:
        gpu: "true"                 # 只调度到有 GPU 标签的节点
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports:
            - containerPort: 11434
          resources:
            limits:
              nvidia.com/gpu: 1     # 请求 1 块 NVIDIA GPU
          volumeMounts:
            - name: ollama-models
              mountPath: /root/.ollama
  volumeClaimTemplates:             # StatefulSet 专属：每个 Pod 自动创建 PVC
    - metadata:
        name: ollama-models
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 20Gi           # 模型文件存储（7B q4 ≈ 4GB, 多个模型共存）
```

**为什么用 StatefulSet 而不是 Deployment：**

| 特性 | Deployment | StatefulSet |
|------|-----------|-------------|
| Pod 标识 | 随机名 | 固定序号 (ollama-0, ollama-1) |
| 存储 | 所有 Pod 共享同一 PVC | 每个 Pod 独立 PVC（通过 volumeClaimTemplates） |
| 重建行为 | 新 Pod 可能调度到不同节点 | 尽量保持在同一节点，复用原有 PVC |
| 适用场景 | 无状态服务 | 有状态服务（模型文件需持久化） |

Ollama 的模型文件存储在 `/root/.ollama`，需要持久化以避免每次 Pod 重建都重新下载模型（几 GB）。StatefulSet 确保 Pod 重建后能重新挂载原来的 PVC。

**GPU 调度前提**：集群需要安装 `nvidia-device-plugin` DaemonSet，它会在 GPU 节点上注册 `nvidia.com/gpu` 扩展资源。

### 8.4 HPA 策略

#### API Server HPA

```yaml
# k8s/api-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 2        # 最少 2 个副本（高可用）
  maxReplicas: 5        # 最多 5 个副本（成本控制）
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70     # CPU 使用率 > 70% 时扩容
```

#### Celery Worker HPA

```yaml
# k8s/worker-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: worker
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**扩容/缩容行为：**

```
CPU 使用率:
  ───────────┐
             │  > 70%
             ├──────────────────────────────────────▶ 增加 Pod
             │
  ───────────┤
             │  ≤ 70%
             ├──────────────────────────────────────▶ 保持
             │
  ───────────┤
             │  远低于 70% (持续 5 分钟)
             ├──────────────────────────────────────▶ 减少 Pod (默认 5 分钟冷却)
             │
  ───────────┘
```

### 8.5 Jaeger 追踪后端

```yaml
# k8s/jaeger-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: jaeger
          image: jaegertracing/all-in-one:latest
          ports:
            - containerPort: 16686    # Jaeger UI
              name: ui
            - containerPort: 4317     # OTLP gRPC 接收端
              name: otlp-grpc
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
```

`jaeger-all-in-one` 集成了 collector、storage、query、UI，适合开发和小规模生产。大规模部署应拆分为独立组件 + Elasticsearch/Cassandra 后端。

### 8.6 Docker Compose (本地开发)

```yaml
# docker-compose.yml
services:
  api:
    build: .
    environment:
      LLM_PROVIDER: ollama
      EMBEDDING_PROVIDER: ollama
      OLLAMA_BASE_URL: http://ollama:11434
      OTEL_ENABLED: "true"
      OTEL_EXPORTER_ENDPOINT: http://jaeger:4317
    depends_on: [postgres, redis, ollama]

  worker:
    build: .
    command: celery -A app.workers.celery_app.celery_app worker --loglevel=info

  ollama:
    image: ollama/ollama:latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]        # Docker GPU 直通

  jaeger:
    image: jaegertracing/all-in-one:latest
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"                    # Jaeger UI
      - "4317:4317"                      # OTLP gRPC
```

**Docker Compose vs K8s 配置差异：**

| 维度 | Docker Compose | K8s |
|------|---------------|-----|
| 服务发现 | Docker DNS (`ollama:11434`) | K8s Service DNS (`ollama.rag-platform.svc.cluster.local`) |
| GPU | `deploy.resources.reservations.devices` | `resources.limits.nvidia.com/gpu` |
| 配置管理 | `environment` 直接写在 YAML | ConfigMap + Secret |
| 扩缩容 | 手动 `docker-compose scale` | HPA 自动 |
| 持久化 | Docker volumes | PVC (PersistentVolumeClaim) |

### 8.7 面试讨论要点

> **Q: 为什么 API Server 最少 2 个副本？**
>
> A: 单副本部署存在单点故障——Pod 重启期间（滚动更新、节点故障、OOM Kill）服务中断。2 个副本确保任何时候至少有 1 个 Pod 可以服务。配合 `PodDisruptionBudget` 可以进一步保证滚动更新时的可用性。

> **Q: HPA 只基于 CPU 够不够？**
>
> A: 对于 CPU 密集型的 API Server 够用。但对于 Celery Worker，更好的指标是 Redis 队列长度：
> ```yaml
> metrics:
>   - type: External
>     external:
>       metric:
>         name: redis_queue_length
>         selector:
>           matchLabels:
>             queue: celery
>       target:
>         type: AverageValue
>         averageValue: 10        # 每个 worker 队列积压超过 10 则扩容
> ```
> 需要安装 Prometheus Adapter 将 Prometheus 指标暴露为 K8s custom metrics。

> **Q: Ollama 为什么不做 HPA？**
>
> A: GPU 资源昂贵且有限，自动扩容可能导致 GPU 资源耗尽影响其他任务。更好的策略是使用请求队列 + 固定副本数，通过 Token Bucket 限流控制并发。如果需要弹性 GPU 推理，应考虑 vLLM + NVIDIA Triton 等专业推理服务。

---

## 附录：组件交互总览

```
                                    ┌──────────────┐
                                    │    Client     │
                                    └──────┬───────┘
                                           │
                                    ┌──────▼───────┐
                                    │ RateLimiter   │ ← Token Bucket (30 RPM)
                                    │ Middleware    │
                                    └──────┬───────┘
                                           │
                              ┌────────────▼────────────┐
                              │      FastAPI Router      │
                              │  /api/v1/chat            │
                              │  /api/v1/search          │
                              │  /api/v1/infra/*         │
                              └────────────┬────────────┘
                                           │
                   ┌───────────────────────▼───────────────────────┐
                   │              ProviderRegistry                  │
                   │  (Thread-safe Singleton, Double-Checked Lock)  │
                   ├───────────────────────────────────────────────┤
                   │                                                │
          ┌────────▼────────┐                           ┌──────────▼──────────┐
          │   LLM Provider   │                           │ Embedding Provider   │
          │                  │                           │                      │
          │  ┌─────────┐    │                           │ ┌──────────────┐     │
          │  │ Ollama   │    │                           │ │ Ollama Embed │     │
          │  └─────────┘    │                           │ └──────────────┘     │
          │  ┌─────────┐    │                           │ ┌──────────────┐     │
          │  │  API     │    │                           │ │ Legacy Embed │     │
          │  └─────────┘    │                           │ │ (adapter)    │     │
          │  ┌─────────┐    │                           │ └──────────────┘     │
          │  │ AB Test  │    │                           └─────────────────────┘
          │  │ (wraps 2)│    │
          │  └─────────┘    │
          └─────────────────┘
                   │
      ┌────────────┼────────────┐
      │            │            │
      ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│Prometheus │ │  OTel    │ │ Circuit  │
│ Metrics   │ │ Tracing  │ │ Breaker  │
│           │ │          │ │          │
│ Histogram │ │ Jaeger   │ │ 3-state  │
│ Counter   │ │ Spans    │ │ machine  │
│ Gauge     │ │ Propagate│ │          │
└──────────┘ └──────────┘ └──────────┘
```

---

## 附录：文件索引

| 文件路径 | 职责 |
|---------|------|
| `app/infra/model_provider.py` | LLMProvider / EmbeddingProvider ABC 定义，LLMResponse 数据类 |
| `app/infra/ollama_provider.py` | Ollama LLM & Embedding Provider 实现 |
| `app/infra/api_provider.py` | OpenAI 兼容 API Provider 实现 |
| `app/infra/provider_registry.py` | Provider 注册表（单例）、ABTestingLLMProvider、_LegacyEmbeddingProvider |
| `app/infra/tracing.py` | OpenTelemetry 初始化、trace_span helper、Celery context propagation |
| `app/infra/rate_limiter.py` | Token Bucket 限流器 + FastAPI Middleware |
| `app/infra/circuit_breaker.py` | 三状态熔断器 |
| `app/core/metrics.py` | Prometheus 指标定义 |
| `app/core/config.py` | pydantic-settings 配置（所有 infra 相关环境变量） |
| `app/main.py` | FastAPI 应用创建、健康检查端点、中间件注册 |
| `app/api/routes_infra.py` | Infra API 端点（模型列表、健康检查、AB 配置/统计） |
| `app/services/llm_service.py` | LLM 业务逻辑（通过 ProviderRegistry 获取 Provider） |
| `k8s/*.yaml` | Kubernetes 部署清单 |
| `docker-compose.yml` | 本地开发环境编排 |
