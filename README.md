# 分布式 RAG 检索与推理平台

## 1. 项目简介

这是一个面向 **AI Infra / RAG 工程化** 场景设计的全栈项目，不仅实现了完整的 RAG 检索与问答链路，还构建了生产级的 AI 基础设施层：

- **可插拔模型服务**：支持 Ollama（本地 GPU）、DeepSeek、OpenAI 兼容 API 等多种 Provider
- **模型 A/B 测试**：支持同时运行两个模型版本，按权重分配流量并收集指标
- **分布式追踪**：OpenTelemetry 全链路追踪（API → 检索 → Embedding → LLM）
- **Prometheus 指标**：模型推理延迟、Token 吞吐、健康状态、限流统计等 AI 特有指标
- **限流与熔断**：Token Bucket 限流器 + 三状态断路器保障服务稳定性
- **Kubernetes 部署**：完整 K8s 清单，包含 GPU 调度、HPA 自动伸缩、健康探针

核心 RAG 能力：

- 文档上传、解析、切块、embedding 生成与向量入库
- `vector`、`lexical`、`hybrid` 三种检索模式
- RRF 融合、Rerank、基于上下文的 LLM 问答
- 异步任务调度、搜索缓存、内容去重
- 数据库迁移、离线评测与在线 benchmark

项目整体围绕 `FastAPI + PostgreSQL + LanceDB + Celery + Redis + Ollama` 构建。

### 适合方向

- AI Infra / AI 平台工程
- RAG / 检索增强生成
- 推理服务化 / 模型服务
- 分布式系统 / 基础设施后端
- 数据平台 / 数据工程

## 2. 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn + Pydantic |
| 业务数据库 | PostgreSQL (prod) / SQLite (dev)，SQLAlchemy + Alembic |
| 向量数据库 | LanceDB + PyArrow |
| 任务队列 | Celery + Redis |
| 缓存 | Redis（JSON 序列化，SHA256 缓存 key，命名空间失效） |
| 模型服务 | Ollama (本地 GPU) / OpenAI 兼容 API (DeepSeek, vLLM 等) |
| Embedding | Ollama (`nomic-embed-text`) / sentence-transformers / 本地 hash |
| LLM | 可插拔 Provider：`ollama` / `api` / `ab_test` |
| 分布式追踪 | OpenTelemetry + Jaeger |
| 监控指标 | Prometheus |
| 容器化 | Docker Compose (dev) / Kubernetes (prod) |
| 文档处理 | PyPDF, plain text, markdown, source code (.py, .rs) |

## 3. 系统架构

```text
                          ┌──────────────────────────────────────────────────┐
                          │                 Client / Demo UI                 │
                          └─────────────────────┬────────────────────────────┘
                                                │
                          ┌─────────────────────▼────────────────────────────┐
                          │            FastAPI API (Rate Limiter)             │
                          │     OpenTelemetry Instrumentation Middleware      │
                          ├──────────────────────────────────────────────────┤
                          │  routes_docs  routes_query  routes_infra         │
                          │  routes_tasks              /health /health/ready │
                          └──┬──────┬──────┬──────┬──────┬──────────────────┘
                             │      │      │      │      │
              ┌──────────────┘      │      │      │      └──────────────┐
              ▼                     ▼      │      ▼                     ▼
        ┌──────────┐     ┌──────────────┐  │  ┌──────────┐     ┌──────────────┐
        │PostgreSQL│     │   LanceDB    │  │  │  Redis   │     │    Jaeger    │
        │          │     │  (Vectors)   │  │  │(Cache/MQ)│     │  (Tracing)  │
        └──────────┘     └──────────────┘  │  └──────────┘     └──────────────┘
                                           │
                    ┌──────────────────────┘
                    ▼
          ┌──────────────────────────────────────────┐
          │           Provider Registry               │
          │  ┌──────────┐ ┌──────────┐ ┌───────────┐ │
          │  │  Ollama   │ │ API/DS   │ │ A/B Test  │ │
          │  │ Provider  │ │ Provider │ │ Provider  │ │
          │  └─────┬─────┘ └────┬─────┘ └─────┬────┘ │
          └────────┼────────────┼──────────────┼──────┘
                   ▼            ▼              ▼
          ┌──────────────┐ ┌──────────┐ ┌──────────────┐
          │   Ollama     │ │ DeepSeek │ │  Model A/B   │
          │  (Local GPU) │ │   API    │ │  两模型分流  │
          └──────────────┘ └──────────┘ └──────────────┘

                    ┌───────────────────────┐
                    │    Celery Workers      │
                    │  ┌────────────────┐    │
                    │  │ Ingestion Task │    │
                    │  │ Embedding Task │    │
                    │  └────────────────┘    │
                    └───────────────────────┘
```

### 3.1 模块分层

```text
app/
├── api/                  # 路由层
│   ├── routes_docs.py    # 文档管理 CRUD
│   ├── routes_query.py   # 检索与问答
│   ├── routes_tasks.py   # 任务管理
│   ├── routes_infra.py   # AI Infra 管理端点
│   └── deps.py           # 依赖注入
├── infra/                # AI 基础设施层
│   ├── model_provider.py # Provider 抽象基类
│   ├── ollama_provider.py# Ollama 实现 (LLM + Embedding)
│   ├── api_provider.py   # OpenAI 兼容 API 实现
│   ├── provider_registry.py # Provider 注册、路由、A/B 测试
│   ├── tracing.py        # OpenTelemetry 初始化与 Span 工具
│   ├── rate_limiter.py   # Token Bucket 限流中间件
│   └── circuit_breaker.py# 三状态断路器
├── services/             # 业务逻辑层
│   ├── retrieval_service.py # 检索编排 (vector/lexical/hybrid)
│   ├── llm_service.py    # LLM 问答（委托给 Provider）
│   ├── embedding_service.py # Embedding 生成
│   ├── bm25_service.py   # 词法检索评分
│   ├── hybrid_service.py # RRF 融合
│   ├── rerank_service.py # 重排
│   ├── chunk_service.py  # 切块
│   ├── document_service.py  # 文档管理
│   └── cache_service.py  # Redis 缓存
├── workers/              # Celery 异步任务
├── db/                   # 数据库连接
├── models/               # SQLAlchemy ORM
├── schemas/              # Pydantic 请求/响应
├── core/                 # 配置、日志、指标
└── main.py               # 应用入口
```

### 3.2 请求流程

**上传入库**：

```
Client → routes_docs → DocumentService → content_hash 去重 → 写入 PostgreSQL
  → Celery ingest_task → 文本抽取 + 切块 → 写入 chunks
  → Celery embed_task → EmbeddingProvider → 写入 LanceDB → 清缓存
```

**搜索问答**：

```
Client → routes_query → RetrievalService
  → 检查 Redis 缓存
  → 若未命中：EmbeddingProvider → LanceDB 向量检索
  → (hybrid 模式) BM25 词法检索 → RRF 融合
  → Rerank 重排 → 写入缓存
  → (chat 端点) LLMProvider → 生成 grounded answer
  → 返回结果 + citations + model_version
```

## 4. AI Infra 核心能力

### 4.1 可插拔 Model Provider 架构

通过抽象的 `LLMProvider` / `EmbeddingProvider` 接口，支持多种模型服务后端：

```text
LLM_PROVIDER 环境变量
  ├── "ollama"    → OllamaLLMProvider      (本地 Ollama REST API)
  ├── "api"       → APILLMProvider         (OpenAI 兼容: DeepSeek, vLLM 等)
  ├── "deepseek"  → APILLMProvider         (别名)
  └── "ab_test"   → ABTestingLLMProvider   (包装两个模型，按权重分流)

EMBEDDING_PROVIDER 环境变量
  ├── "ollama"    → OllamaEmbeddingProvider (Ollama /api/embed)
  └── "legacy"    → 本地 hash / sentence-transformers (进程内)
```

**核心设计**：

- `model_provider.py`：定义 `LLMProvider` 和 `EmbeddingProvider` 两个 ABC
- `provider_registry.py`：单例注册中心，根据配置创建对应 Provider
- 每个 Provider 实现 `health_check()` 方法，支持健康探测
- Ollama Provider 支持启动时模型预热（warmup）

### 4.2 模型 A/B 测试

设置 `LLM_PROVIDER=ab_test` 后，系统可同时运行两个模型版本：

- 根据 `AB_TRAFFIC_SPLIT` (默认 80/20) 随机路由请求
- 每个模型独立记录推理延迟、Token 数等指标
- `/api/v1/infra/ab/config` 支持动态调整流量比例
- `/api/v1/infra/ab/stats` 查看 A/B 测试统计
- Chat 响应中包含 `model_version` 字段标记使用的模型

### 4.3 分布式追踪 (OpenTelemetry)

设置 `OTEL_ENABLED=true` 启用全链路追踪：

- FastAPI 中间件自动为每个请求创建 Span
- `retrieval_service.search()` 记录 search_mode、top_k
- Ollama/API Provider 记录 model、token_count、latency
- Celery Worker 记录 document_id、chunk_count
- 通过 OTLP gRPC 导出到 Jaeger，可在 Jaeger UI 查看完整链路

### 4.4 Prometheus 指标

在原有业务指标基础上，新增 AI Infra 特有指标：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `rag_model_inference_seconds` | Histogram | 模型推理延迟 (provider/model/operation) |
| `rag_model_tokens_total` | Counter | Token 吞吐 (model/direction: input/output) |
| `rag_model_health_status` | Gauge | 模型服务健康 (1=健康, 0=异常) |
| `rag_rate_limit_rejected_total` | Counter | 限流拒绝请求数 |
| `rag_embedding_batch_size` | Histogram | Embedding 批处理大小 |

### 4.5 限流器 (Token Bucket)

- 基于内存的 Token Bucket 实现，作为 FastAPI 中间件全局生效
- 可配置 RPM (每分钟请求数)，默认 30
- 健康检查和指标端点自动豁免
- 超限请求返回 HTTP 429

### 4.6 熔断器 (Circuit Breaker)

三状态断路器保护模型服务调用：

```text
CLOSED ──(连续 N 次失败)──→ OPEN ──(等待 recovery_timeout)──→ HALF_OPEN
  ↑                                                              │
  └───────────────(成功)──────────────────────────────────────────┘
                                 │(失败)
                                 └──→ OPEN
```

- 可配置失败阈值、恢复超时、半开状态最大尝试次数
- 应用于 LLM 和 Embedding Provider 调用

### 4.7 健康检查

| 端点 | 用途 | 检查内容 |
|------|------|----------|
| `GET /health` | K8s Liveness Probe | 浅检查，服务存活即返回 OK |
| `GET /health/ready` | K8s Readiness Probe | 深度检查：数据库 + Redis + 所有模型服务 |

## 5. Kubernetes 部署

项目提供完整的 K8s 清单 (`k8s/` 目录)：

```text
k8s/
├── namespace.yaml           # rag-platform 命名空间
├── configmap.yaml           # 所有环境变量
├── secret.yaml              # API Key (base64)
├── api-deployment.yaml      # FastAPI (2 replicas, readiness/liveness probes)
├── api-service.yaml         # ClusterIP:8000
├── api-hpa.yaml             # HPA: 2-5 replicas, 70% CPU
├── worker-deployment.yaml   # Celery Worker (2 replicas)
├── worker-hpa.yaml          # HPA: 2-5 replicas, 70% CPU
├── ollama-deployment.yaml   # StatefulSet, nvidia.com/gpu: 1, nodeSelector
├── ollama-service.yaml      # ClusterIP:11434
├── postgres-deployment.yaml # PostgreSQL 16
├── postgres-service.yaml    # ClusterIP:5432
├── postgres-pvc.yaml        # 10Gi
├── redis-deployment.yaml    # Redis 7
├── redis-service.yaml       # ClusterIP:6379
├── lancedb-pvc.yaml         # 20Gi
├── jaeger-deployment.yaml   # Jaeger all-in-one
└── jaeger-service.yaml      # UI:16686, OTLP:4317
```

**关键配置**：

- Ollama Pod：`nvidia.com/gpu: 1`，`nodeSelector: gpu: "true"`
- API Pod：readinessProbe → `/health/ready`，livenessProbe → `/health`
- HPA：API 和 Worker 基于 CPU 自动伸缩 (2-5 replicas)

## 6. 检索模式设计

### 6.1 vector（向量检索）

使用 Embedding 后的向量进行余弦相似度近邻搜索。

- **优点**：语义理解能力强，适合表达方式差异大的问题
- **缺点**：对精确术语、字段名不一定稳定

### 6.2 lexical（词法检索）

使用 BM25 风格词法评分（TF-IDF，可配置 k1/b 参数）。

- **优点**：对关键词、术语、代码标识符更敏感
- **缺点**：对同义表达和语义近似不如向量检索

### 6.3 hybrid（混合检索）

融合 vector 与 lexical 两路结果，使用 RRF (Reciprocal Rank Fusion)。

- **为什么用 RRF**：不要求不同检索器的分数在同一量纲，比简单加权平均更稳健

## 7. 数据模型设计

### 7.1 PostgreSQL 表

| 表名 | 核心字段 | 用途 |
|------|----------|------|
| `documents` | id, filename, content_type, storage_path, file_size, content_hash, knowledge_base, status | 文档元数据、去重判断、状态跟踪 |
| `chunks` | id, document_id, chunk_index, content, token_count, source, status | 切块管理、词法检索输入 |
| `tasks` | id, document_id, task_type, status, celery_task_id, error_message, retry_count | 异步任务追踪、重试控制 |

### 7.2 LanceDB 表

| 字段 | 类型 | 说明 |
|------|------|------|
| chunk_id | string | 关联 PostgreSQL chunk |
| document_id | string | 文档 ID |
| knowledge_base | string | 知识库 |
| text | string | 文本内容 |
| vector | float[] | Embedding 向量 |
| source | string | 来源 |
| chunk_index | int | 块序号 |

### 7.3 为什么双数据库

- PostgreSQL 负责事务、一致性、管理查询 → 结构化业务数据
- LanceDB 负责向量存储与语义检索 → 检索性能
- 分层设计更接近真实生产系统架构

## 8. 稳定性与工程化设计

| 能力 | 实现方式 |
|------|----------|
| 内容去重 | SHA256 content_hash + knowledge_base 判重 |
| 搜索缓存 | Redis 缓存热门查询结果，TTL 300s |
| 缓存失效 | 索引更新/文档删除后按命名空间清缓存 |
| 任务重试 | retry_count + 显式 retry API |
| 删除一致性 | 删文档时同步清理 PostgreSQL + LanceDB + Redis |
| 限流保护 | Token Bucket 全局限流，超限返回 429 |
| 熔断保护 | Circuit Breaker 防止级联故障 |
| 健康探测 | 浅/深两级健康检查，K8s 原生集成 |

## 9. 接口总览

### 9.1 文档管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/documents/upload` | 上传文档 |
| GET | `/api/v1/documents` | 列出文档 |
| GET | `/api/v1/documents/dashboard/summary` | Dashboard 概览 |
| GET | `/api/v1/documents/{document_id}` | 获取文档详情 |
| DELETE | `/api/v1/documents/{document_id}` | 删除文档 |

### 9.2 检索与问答

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/search` | 检索（vector/lexical/hybrid） |
| POST | `/api/v1/chat` | 检索 + LLM 问答 |

### 9.3 任务管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/tasks/{task_id}` | 查看任务状态 |
| POST | `/api/v1/tasks/{task_id}/retry` | 重试失败任务 |

### 9.4 AI Infra 管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/infra/models` | 列出已加载模型 |
| GET | `/api/v1/infra/models/health` | 模型深度健康检查 |
| POST | `/api/v1/infra/ab/config` | 动态调整 A/B 流量比例 |
| GET | `/api/v1/infra/ab/stats` | A/B 测试统计 |
| GET | `/api/v1/infra/metrics/models` | 模型级别指标摘要 |

### 9.5 观测

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | Liveness 探针 |
| GET | `/health/ready` | Readiness 探针 |
| GET | `/metrics` | Prometheus 指标 |
| GET | `/` | 演示页面 |

## 10. 接口示例

### 10.1 上传文档

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents/upload \
  -F "file=@./README.md" \
  -F "knowledge_base=demo"
```

### 10.2 搜索

```bash
curl -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何通过异步流水线提升上传吞吐？",
    "top_k": 5,
    "knowledge_base": "demo",
    "search_mode": "hybrid",
    "use_rerank": true
  }'
```

### 10.3 问答（含模型版本）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "这个系统为什么要把上传和索引构建解耦？",
    "top_k": 5,
    "search_mode": "hybrid"
  }'
# 响应包含 "model_version" 字段，标记使用的模型
```

### 10.4 查看 A/B 测试状态

```bash
# 查看统计
curl http://127.0.0.1:8000/api/v1/infra/ab/stats

# 调整流量比例
curl -X POST http://127.0.0.1:8000/api/v1/infra/ab/config \
  -H "Content-Type: application/json" \
  -d '{"traffic_split": 0.5}'
```

### 10.5 模型健康检查

```bash
curl http://127.0.0.1:8000/api/v1/infra/models/health
```

## 11. 环境配置

复制 `.env.example` 到 `.env` 并配置：

### 11.1 核心配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite:///./data/app.db` | 数据库连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 地址 |
| `CELERY_TASK_ALWAYS_EAGER` | `true` | true=同步模式，false=需 Redis |
| `CHUNK_SIZE` | `600` | 切块大小 |
| `CHUNK_OVERLAP` | `100` | 切块重叠 |
| `EMBEDDING_DIM` | `64` | 向量维度 |

### 11.2 模型服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `deepseek` | 模型后端：`ollama` / `api` / `deepseek` / `ab_test` |
| `LLM_API_KEY` | - | API Key (api/deepseek 模式) |
| `LLM_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 地址 |
| `OLLAMA_LLM_MODEL` | `qwen2.5:7b-instruct-q4_K_M` | Ollama LLM 模型 |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama Embedding 模型 |
| `EMBEDDING_PROVIDER` | `legacy` | Embedding 后端：`ollama` / `legacy` |

### 11.3 A/B 测试配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AB_MODEL_A` | `qwen2.5:7b` | A 模型 |
| `AB_MODEL_B` | `qwen2.5:3b` | B 模型 |
| `AB_TRAFFIC_SPLIT` | `0.8` | A 模型流量比例 (80%) |

### 11.4 可观测性配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OTEL_ENABLED` | `false` | 启用 OpenTelemetry 追踪 |
| `OTEL_EXPORTER_ENDPOINT` | `http://localhost:4317` | OTLP gRPC 端点 |
| `RATE_LIMIT_ENABLED` | `true` | 启用限流 |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | 每分钟最大请求数 |

## 12. 快速开始

### 12.1 本地开发模式 (SQLite)

```bash
# 克隆项目
git clone <repo-url>
cd rag-platform

# 安装依赖
pip install -r requirements.txt

# 配置环境
cp .env.example .env
# 编辑 .env 设置 LLM_API_KEY

# 初始化数据库
alembic upgrade head

# 导入演示数据
python scripts/load_demo_docs.py

# 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 12.2 Ollama 本地 GPU 模式

```bash
# 安装并启动 Ollama
ollama serve

# 拉取模型
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama pull nomic-embed-text

# 配置 .env
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434

# 启动
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 12.3 Docker Compose 模式

```bash
# 启动所有服务 (API + Worker + PostgreSQL + Redis + Ollama + Jaeger)
docker-compose up

# 拉取 Ollama 模型 (首次启动后)
docker exec -it rag-platform-ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker exec -it rag-platform-ollama ollama pull nomic-embed-text

# 访问
# API:    http://localhost:8000
# Jaeger: http://localhost:16686
```

### 12.4 Kubernetes 部署

```bash
# 部署所有组件
kubectl apply -f k8s/

# 检查状态
kubectl -n rag-platform get pods

# 查看 API 日志
kubectl -n rag-platform logs -l app=api -f
```

## 13. 验证方案

### 13.1 向后兼容验证

```bash
# DeepSeek API 模式仍正常工作
LLM_PROVIDER=deepseek pytest tests/
```

### 13.2 Ollama 验证

```bash
# 设置 Ollama 模式
LLM_PROVIDER=ollama EMBEDDING_PROVIDER=ollama \
  uvicorn app.main:app --host 127.0.0.1 --port 8000

# 测试 chat
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是 RAG？", "top_k": 5}'
```

### 13.3 追踪验证

```bash
# 启动 Jaeger
docker-compose up jaeger

# 启用追踪
OTEL_ENABLED=true OTEL_EXPORTER_ENDPOINT=http://localhost:4317 \
  uvicorn app.main:app --host 127.0.0.1 --port 8000

# 发几个请求后，访问 Jaeger UI
open http://localhost:16686
```

### 13.4 指标验证

```bash
curl http://127.0.0.1:8000/metrics | grep rag_model
```

### 13.5 限流验证

```bash
# 快速发送超过 RPM 的请求
for i in $(seq 1 35); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://127.0.0.1:8000/api/v1/search \
    -H "Content-Type: application/json" \
    -d '{"query": "test", "top_k": 1}'
done
# 后几个请求应返回 429
```

### 13.6 A/B 测试验证

```bash
# 设置 A/B 模式
LLM_PROVIDER=ab_test AB_MODEL_A=qwen2.5:7b AB_MODEL_B=qwen2.5:3b \
  uvicorn app.main:app --host 127.0.0.1 --port 8000

# 发多次请求后查看统计
curl http://127.0.0.1:8000/api/v1/infra/ab/stats
```

## 14. 离线评测与 Benchmark

### 14.1 离线评测

```bash
python scripts/evaluate_retrieval.py
```

### 14.2 在线 Benchmark

```bash
# 启动服务后，在另一个终端
python scripts/benchmark.py
```

### 14.3 验证结果示例

```text
# 离线评测
mode=vector  hit@1=1.00  hit@3=1.00
mode=lexical hit@1=1.00  hit@3=1.00
mode=hybrid  hit@1=1.00  hit@3=1.00

# 在线 benchmark
mode=vector  requests=20 avg=0.0013s p95=0.0019s
mode=lexical requests=20 avg=0.0013s p95=0.0016s
mode=hybrid  requests=20 avg=0.0013s p95=0.0014s
```

## 15. 项目亮点总结

### RAG 工程化

- 完整的文档上传 → 切块 → Embedding → 向量入库 → 检索 → 问答链路
- vector / lexical / hybrid 三种检索模式 + RRF 融合
- 异步任务调度、搜索缓存、内容去重、删除一致性

### AI Infra 能力

- 可插拔 Model Provider 架构，支持 Ollama / API / A/B Test
- OpenTelemetry 全链路分布式追踪
- Prometheus 模型推理指标（延迟、Token 吞吐、健康状态）
- Token Bucket 限流 + Circuit Breaker 熔断
- K8s 完整部署清单（GPU 调度、HPA、健康探针）

### 工程质量

- 双数据库分层设计 (PostgreSQL + LanceDB)
- Alembic 数据库迁移
- 离线评测 + 在线 Benchmark
- Docker Compose + Kubernetes 部署
- 可演示的前端页面

## 16. 面试重点

1. **Model Provider 抽象**：解释为什么需要 Provider 层，如何做到热切换和向后兼容
2. **A/B 测试设计**：如何实现流量分配、指标收集、动态调整
3. **分布式追踪**：OpenTelemetry 在 API + Celery Worker 中的 Span 传播
4. **限流与熔断**：Token Bucket 算法、Circuit Breaker 三状态转换
5. **双数据库分层**：PostgreSQL vs LanceDB 的职责划分
6. **检索策略**：vector / lexical / hybrid 的适用场景，RRF 为什么优于加权平均
7. **K8s 部署**：GPU 调度、HPA 配置、健康探针设计

## 17. 详细文档

- [架构设计文档](docs/architecture.md) — 系统架构、组件交互、数据流详解
- [部署指南](docs/deployment.md) — 本地开发、Docker Compose、K8s 部署完整指南
- [API 参考手册](docs/api-reference.md) — 所有接口的请求/响应格式与示例
- [AI Infra 设计文档](docs/infra-design.md) — Provider 架构、追踪、指标、限流、熔断设计决策
