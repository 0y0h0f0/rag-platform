# RAG Platform 项目简介

> 一个功能完整的检索增强生成（Retrieval-Augmented Generation）平台，从文档上传到智能问答，覆盖 RAG 全链路。

---

## 什么是 RAG？

RAG（Retrieval-Augmented Generation）是一种将**信息检索**与**大语言模型生成**结合的技术范式。传统 LLM 只能依赖训练数据回答问题，而 RAG 允许模型在回答前先从外部知识库中检索相关信息，从而：

- 减少模型幻觉（hallucination）
- 支持私有领域知识问答
- 无需重新训练模型即可更新知识

## 本项目做了什么

RAG Platform 是一个**生产级 RAG 系统的参考实现**，涵盖了从原始文档到智能回答的完整数据流：

```
文档上传 → 文本提取 → 分块 → 向量化 → 索引存储
                                          ↓
用户提问 → 查询向量化 → 多模式检索 → 重排序 → LLM 生成 → 返回回答
```

### 核心能力

| 能力 | 说明 |
|------|------|
| 多格式文档处理 | 支持 PDF、Markdown、纯文本、Python、Rust 源码 |
| 三种检索模式 | 向量检索（余弦相似度）、词法检索（BM25）、混合检索（RRF 融合） |
| 可插拔模型架构 | LLM 和 Embedding 模型均可通过环境变量热切换 |
| 异步任务流水线 | 文档入库通过 Celery 异步处理，API 即时响应 |
| 智能缓存 | Redis 缓存检索结果，SHA256 键 + 命名空间失效 |
| 内容去重 | SHA256 内容哈希，同一知识库内自动跳过重复文档 |
| A/B 测试 | 内置模型 A/B 测试框架，支持动态流量分配 |
| 可观测性 | OpenTelemetry 分布式追踪 + Prometheus 指标 + Jaeger UI |
| 容错机制 | 令牌桶限流 + 三态熔断器 |
| 多环境部署 | 本地 SQLite → Docker Compose → Kubernetes 渐进式部署 |

### 技术选型

```
┌─────────────────────────────────────────────────────────┐
│  前端入口    │  FastAPI + Uvicorn (异步 Web 框架)         │
│  关系数据库  │  PostgreSQL (生产) / SQLite (开发)         │
│  向量数据库  │  LanceDB + PyArrow (嵌入式向量存储)        │
│  任务队列    │  Celery + Redis (异步任务处理)              │
│  缓存层      │  Redis (JSON 序列化, SHA256 键)            │
│  LLM 推理   │  Ollama (本地 GPU) / vLLM / DeepSeek API   │
│  向量化      │  Ollama (nomic-embed-text) / sentence-transformers │
│  可观测性    │  OpenTelemetry → Jaeger + Prometheus       │
│  部署        │  Docker Compose (开发) / Kubernetes (生产)  │
└─────────────────────────────────────────────────────────┘
```

## 快速体验

```bash
# 1. 克隆并安装
git clone https://github.com/0y0h0f0/rag-platform.git
cd rag-platform
pip install -r requirements.txt

# 2. 配置环境
cp .env.example .env
# 编辑 .env，填入 LLM API Key

# 3. 初始化数据库 & 加载演示数据
alembic upgrade head
python scripts/load_demo_docs.py

# 4. 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 5. 试试看
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是 RAG？", "search_mode": "hybrid"}'
```

## 项目结构速览

```
rag-platform/
├── app/
│   ├── api/          # API 路由层 (FastAPI 端点定义)
│   ├── core/         # 核心配置、日志、Prometheus 指标
│   ├── db/           # 数据访问层 (PostgreSQL, LanceDB, Redis)
│   ├── infra/        # AI 基础设施 (Provider 抽象, 追踪, 限流, 熔断)
│   ├── models/       # SQLAlchemy ORM 模型
│   ├── schemas/      # Pydantic 请求/响应模型
│   ├── services/     # 业务逻辑层 (检索, LLM, 分块, 缓存...)
│   └── workers/      # Celery 异步任务
├── docs/             # 技术文档
├── k8s/              # Kubernetes 部署清单
├── scripts/          # 工具脚本 (初始化, 演示数据, 基准测试)
├── tests/            # 测试套件
└── docker-compose.yml
```

## 文档导航

| 文档 | 内容 | 适合谁 |
|------|------|--------|
| [快速上手指南](getting-started.md) | 从零搭建开发环境，运行第一个查询 | 新加入的开发者 |
| [架构设计文档](architecture.md) | 分层架构、数据流、设计决策 | 想理解系统设计的开发者 |
| [服务层技术文档](services.md) | 检索、分块、BM25、混合检索等核心算法详解 | 想深入理解业务逻辑的开发者 |
| [数据层技术文档](data-layer.md) | PostgreSQL、LanceDB、Redis 的使用方式和设计 | 关注数据存储的开发者 |
| [异步任务技术文档](workers.md) | Celery 任务流水线、入库和向量化流程 | 关注后台处理的开发者 |
| [AI Infra 设计文档](infra-design.md) | Provider 抽象、A/B 测试、追踪、限流、熔断 | 关注 AI 基础设施的开发者 |
| [API 参考文档](api-reference.md) | 所有 API 端点的详细说明、请求/响应示例 | 前端开发者、API 调用者 |
| [部署指南](deployment.md) | 本地、Docker Compose、Kubernetes 部署方式 | 运维工程师、DevOps |
| [测试指南](testing.md) | 测试策略、运行方式、编写规范 | 所有开发者 |

## 适合谁

- **后端工程师**：学习如何构建一个完整的 RAG 系统
- **AI 工程师**：了解 LLM 应用的工程化实践（Provider 抽象、A/B 测试、可观测性）
- **基础设施工程师**：参考限流、熔断、分布式追踪等 Infra 组件的实现
- **学生/求职者**：作为技术面试的项目展示，涵盖分布式系统的多个核心话题

## License

MIT
