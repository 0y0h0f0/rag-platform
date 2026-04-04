# RAG Platform 快速上手指南

> 面向新加入团队的开发者，从零搭建开发环境并运行第一个查询。

---

## 目录

1. [前置知识](#1-前置知识)
2. [环境准备](#2-环境准备)
3. [项目安装](#3-项目安装)
4. [理解项目结构](#4-理解项目结构)
5. [运行第一个查询](#5-运行第一个查询)
6. [常见工作流](#6-常见工作流)
7. [开发调试技巧](#7-开发调试技巧)
8. [下一步学习](#8-下一步学习)

---

## 1. 前置知识

在开始之前，确保你对以下概念有基本了解：

| 概念 | 为什么需要 | 快速学习资源 |
|------|-----------|-------------|
| Python 3.11+ | 项目主语言 | [Python 官方教程](https://docs.python.org/3/tutorial/) |
| FastAPI | Web 框架 | [FastAPI 官方文档](https://fastapi.tiangolo.com/) |
| SQLAlchemy | ORM 框架 | [SQLAlchemy 教程](https://docs.sqlalchemy.org/en/20/tutorial/) |
| REST API | 接口规范 | 理解 HTTP 方法、状态码、JSON 格式即可 |
| 向量数据库 | 存储和检索向量 | 了解 "向量相似度搜索" 的基本概念 |

**可选但有帮助的知识：**
- Docker & Docker Compose（容器化部署时需要）
- Redis（理解缓存和消息队列）
- Celery（异步任务框架）

---

## 2. 环境准备

### 2.1 安装 Python

```bash
# 检查 Python 版本（需要 3.11+）
python3 --version

# 如果版本过低，推荐使用 pyenv 或 conda 管理
# 使用 conda：
conda create -n rag python=3.11 -y
conda activate rag
```

### 2.2 安装 Git

```bash
git --version
# 如果未安装：sudo apt install git (Ubuntu) 或 brew install git (macOS)
```

### 2.3 (可选) 安装 Docker

仅在需要 Docker Compose 部署时才需要：

```bash
docker --version
docker compose version
```

---

## 3. 项目安装

### 3.1 克隆项目

```bash
git clone https://github.com/0y0h0f0/rag-platform.git
cd rag-platform
```

### 3.2 创建虚拟环境并安装依赖

```bash
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

> **依赖安装耗时约 2-5 分钟**，其中 `sentence-transformers` 和 `torch` 较大。

### 3.3 配置环境变量

```bash
cp .env.example .env
```

打开 `.env` 文件，关注以下关键配置：

```ini
# === 数据库 ===
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/rag_platform

# === LLM 模型 ===
LLM_PROVIDER=deepseek                   # 使用 DeepSeek API（最简单的入门方式）
LLM_API_KEY=your-api-key-here           # ← 替换为你的 API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# === Embedding ===
EMBEDDING_PROVIDER=legacy               # 使用本地哈希嵌入（无需额外模型）
EMBEDDING_BACKEND=local
EMBEDDING_DIM=64

# === 任务队列 ===
CELERY_TASK_ALWAYS_EAGER=true           # 同步执行任务，无需 Redis/Celery Worker
```

> **提示：** 如果没有 DeepSeek API Key，可以先只用检索功能（`/search`），跳过问答功能（`/chat`）。

### 3.4 初始化数据库

```bash
# 创建数据目录
mkdir -p data/uploads

# 运行数据库迁移（创建表结构）
alembic upgrade head
```

### 3.5 加载演示数据

```bash
python scripts/load_demo_docs.py
```

这会创建 3 个演示文档（分布式系统笔记、RAG 笔记、LanceDB 笔记），并将它们分块、向量化、索引到 LanceDB。

### 3.6 启动服务

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

`--reload` 参数会在代码修改后自动重启服务。

### 3.7 验证

```bash
# 健康检查
curl http://127.0.0.1:8000/health
# 期望输出：{"status":"ok"}

# 访问演示页面
# 浏览器打开 http://127.0.0.1:8000/

# 访问 API 文档（自动生成的 Swagger UI）
# 浏览器打开 http://127.0.0.1:8000/docs
```

---

## 4. 理解项目结构

```
rag-platform/
├── app/                         # 应用代码主目录
│   ├── main.py                  # ★ 入口文件，创建 FastAPI 应用
│   ├── api/                     # API 路由层（HTTP 端点定义）
│   │   ├── deps.py              #   依赖注入工厂
│   │   ├── routes_docs.py       #   文档管理 API
│   │   ├── routes_query.py      #   ★ 搜索和问答 API（核心）
│   │   ├── routes_tasks.py      #   异步任务状态 API
│   │   └── routes_infra.py      #   模型管理 API
│   ├── services/                # ★ 业务逻辑层（核心算法所在）
│   │   ├── retrieval_service.py #   ★ 检索编排器（最重要的文件之一）
│   │   ├── llm_service.py       #   LLM 调用 + Prompt 构建
│   │   ├── embedding_service.py #   文本向量化
│   │   ├── chunk_service.py     #   文本提取和分块
│   │   ├── bm25_service.py      #   BM25 词法检索
│   │   ├── hybrid_service.py    #   RRF 混合检索融合
│   │   ├── rerank_service.py    #   结果重排序
│   │   ├── cache_service.py     #   Redis 缓存
│   │   └── document_service.py  #   文档 CRUD
│   ├── infra/                   # AI 基础设施层
│   │   ├── model_provider.py    #   Provider 抽象基类
│   │   ├── ollama_provider.py   #   Ollama 实现
│   │   ├── api_provider.py      #   OpenAI 兼容 API 实现
│   │   ├── provider_registry.py #   Provider 注册中心
│   │   ├── tracing.py           #   分布式追踪
│   │   ├── rate_limiter.py      #   限流器
│   │   └── circuit_breaker.py   #   熔断器
│   ├── db/                      # 数据访问层
│   │   ├── postgres.py          #   SQLAlchemy 引擎/Session
│   │   ├── lancedb_client.py    #   LanceDB 向量操作
│   │   └── redis_client.py      #   Redis 连接
│   ├── models/                  # ORM 模型（数据库表定义）
│   │   ├── document.py          #   Document 表
│   │   ├── chunk.py             #   Chunk 表
│   │   └── task.py              #   TaskRecord 表
│   ├── schemas/                 # Pydantic Schema（请求/响应格式）
│   │   ├── doc_schema.py        #   文档相关
│   │   ├── query_schema.py      #   搜索/问答相关
│   │   └── task_schema.py       #   任务相关
│   ├── core/                    # 核心基础设施
│   │   ├── config.py            #   ★ 全局配置（所有环境变量在这里定义）
│   │   ├── logger.py            #   日志配置
│   │   └── metrics.py           #   Prometheus 指标定义
│   ├── workers/                 # Celery 异步任务
│   │   ├── celery_app.py        #   Celery 配置
│   │   ├── ingestion_tasks.py   #   文档入库任务
│   │   └── embedding_tasks.py   #   向量化任务
│   └── static/                  # 静态文件（前端演示页面）
│       └── index.html
├── alembic/                     # 数据库迁移文件
├── docs/                        # 项目文档
├── k8s/                         # Kubernetes 部署清单
├── scripts/                     # 工具脚本
├── tests/                       # 测试套件
├── .env.example                 # 环境变量模板
├── docker-compose.yml           # Docker 编排配置
└── requirements.txt             # Python 依赖
```

> **★ 标记的文件是最重要的，建议优先阅读。**

---

## 5. 运行第一个查询

### 5.1 检索文档

```bash
# 向量检索
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是向量数据库", "top_k": 3, "search_mode": "vector"}'
```

### 5.2 尝试不同检索模式

```bash
# 词法检索（BM25）
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "分布式系统一致性", "top_k": 3, "search_mode": "lexical"}'

# 混合检索（向量 + BM25，RRF 融合）
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "RAG 检索增强生成", "top_k": 3, "search_mode": "hybrid"}'
```

### 5.3 RAG 问答（需要 LLM API Key）

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "解释一下 RAG 的工作原理", "search_mode": "hybrid"}'
```

### 5.4 上传自己的文档

```bash
# 上传文件
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@你的文档.txt" \
  -F "knowledge_base=my-kb"

# 查看文档列表
curl http://localhost:8000/api/v1/documents

# 在该知识库内检索
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "你的问题", "knowledge_base": "my-kb"}'
```

---

## 6. 常见工作流

### 6.1 修改代码后调试

由于启动时使用了 `--reload` 参数，修改 `app/` 下的代码后服务会自动重启。

### 6.2 数据库变更

如果需要修改数据库模型（`app/models/`），需要创建迁移：

```bash
# 创建迁移文件
alembic revision --autogenerate -m "description of change"

# 应用迁移
alembic upgrade head

# 回退上一次迁移
alembic downgrade -1
```

### 6.3 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行单个测试文件
pytest tests/test_chunk_service.py

# 显示详细输出
pytest tests/ -v
```

### 6.4 运行评估和基准测试

```bash
# 评估检索质量（Hit@1, Hit@3）
python scripts/evaluate_retrieval.py

# 延迟基准测试（需要服务运行中）
python scripts/benchmark.py
```

### 6.5 重置数据（从头开始）

```bash
# 删除所有数据
rm -rf data/

# 重新创建
mkdir -p data/uploads
alembic upgrade head
python scripts/load_demo_docs.py
```

---

## 7. 开发调试技巧

### 7.1 查看 API 文档

FastAPI 自动生成 Swagger UI，浏览器访问 `http://localhost:8000/docs`，可以直接在页面上测试 API。

### 7.2 查看日志

服务启动后，终端会输出实时日志。关注以下关键日志：

```
INFO: providers initialized: llm=api/deepseek-chat, embedding=local/local-hash
INFO: Application startup complete.
```

### 7.3 调试 LLM 调用

如果 `/chat` 返回错误，检查：

1. `.env` 中 `LLM_API_KEY` 是否正确
2. `LLM_BASE_URL` 是否可访问：`curl https://api.deepseek.com/models`

### 7.4 理解数据流

上传文档后跟踪数据流的最佳方式：

1. 连接本地 PostgreSQL，检查 `documents`、`chunks`、`tasks` 表
2. 查看 `data/lancedb/` 目录下的向量数据
3. 使用 `/api/v1/tasks/{task_id}` 查看任务状态

### 7.5 跳过 LLM 只做检索

如果没有 API Key 或不想消耗额度，可以只使用 `/search` 端点。检索功能不依赖 LLM。

---

## 8. 下一步学习

根据你的兴趣方向，选择深入阅读的文档：

| 方向 | 推荐阅读 | 关键文件 |
|------|---------|---------|
| 理解检索算法 | [服务层技术文档](services.md) | `retrieval_service.py`, `bm25_service.py`, `hybrid_service.py` |
| 理解系统架构 | [架构设计文档](architecture.md) | `main.py`, `deps.py` |
| 理解数据存储 | [数据层技术文档](data-layer.md) | `lancedb_client.py`, `postgres.py` |
| 理解 AI Infra | [AI Infra 设计文档](infra-design.md) | `model_provider.py`, `provider_registry.py` |
| 学习部署 | [部署指南](deployment.md) | `docker-compose.yml`, `k8s/` |
| 了解 API | [API 参考文档](api-reference.md) | `routes_query.py`, `routes_docs.py` |

### 推荐阅读顺序

1. **先跑起来** → 本指南
2. **理解全局** → 架构设计文档（`architecture.md`）
3. **深入核心** → 服务层技术文档（`services.md`）
4. **理解 Infra** → AI Infra 设计文档（`infra-design.md`）
5. **实践部署** → 部署指南（`deployment.md`）
