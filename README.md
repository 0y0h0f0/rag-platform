# 分布式 RAG 检索与推理平台

## 1. 项目简介

这是一个面向实习项目场景设计的 RAG 工程化项目，重点不是“接了一个大模型 API”，而是完整实现并验证一条可落地的 AI 检索与问答链路：

- 文档上传与元数据管理
- 文档解析、清洗与切块
- embedding 生成与向量入库
- 在线检索、过滤、重排与问答
- 异步任务调度
- 缓存、去重、任务重试与数据一致性处理
- 数据库迁移、离线评测与在线 benchmark

项目整体围绕 `FastAPI + PostgreSQL + LanceDB + Celery + Redis` 构建，目标是做成一个：

- 能本地运行
- 能演示给面试官看
- 能写进简历
- 能围绕系统设计、稳定性、检索策略和验证流程展开答辩

如果你投递的方向是下面这些，这个项目都比较契合：

- AI Infra / AI 应用工程
- RAG / 检索增强生成
- 推理服务化 / 平台后端
- 数据平台 / 数据工程
- 分布式系统 / 基础设施后端

## 2. 项目想解决什么问题

一个真实可用的知识库问答系统，不只是“把文档送给模型”。它至少要解决下面几类问题：

1. 文档怎么上传、组织和管理
2. 文档怎么切块，才能适配 embedding 和检索
3. embedding 和索引构建如何避免阻塞在线请求
4. 检索时只靠向量是否足够，是否需要关键词能力
5. 检索结果如何结合元数据过滤、重排和回答生成
6. 系统如何处理重复上传、任务失败、缓存失效、数据迁移和性能验证

本项目就是围绕这些问题做的工程实现原型。

## 3. 核心能力概览

当前项目已经具备以下功能：

- 支持文档上传，并记录文件名、大小、类型、知识库归属等元数据
- 支持 `content_hash` 去重，避免重复触发索引任务
- 支持异步 ingestion 流水线，将上传请求与离线索引构建解耦
- 使用 PostgreSQL 管理文档、chunk、任务等业务数据
- 使用 LanceDB 管理向量数据与近邻检索
- 支持 `vector`、`lexical`、`hybrid` 三种检索模式
- 支持简单 rerank 与 grounded answer 生成
- 支持 Redis 搜索缓存和索引更新后的缓存失效
- 支持任务重试与基础监控指标暴露
- 支持 Alembic 迁移脚手架
- 支持 demo 数据导入、离线评测、在线 benchmark
- 提供轻量前端页面作为演示入口

## 4. 技术栈

### 4.1 后端框架

- `Python`
- `FastAPI`
- `Uvicorn`
- `Pydantic`
- `SQLAlchemy`

### 4.2 数据与检索

- `PostgreSQL`：业务元数据、任务状态、chunk 记录
- `LanceDB`：向量数据与向量检索
- `PyArrow`：LanceDB 表结构定义

### 4.3 异步任务与缓存

- `Celery`：任务调度
- `Redis`：broker / result backend / 搜索缓存

### 4.4 迁移、测试与验证

- `Alembic`
- `Pytest`
- `scripts/evaluate_retrieval.py`
- `scripts/benchmark.py`

## 5. 为什么同时使用 PostgreSQL 和 LanceDB

这是项目里最重要的设计之一。

### PostgreSQL 负责

- 文档元数据
- chunk 结构化记录
- 任务状态
- 知识库归属
- 管理型查询与关系约束

### LanceDB 负责

- 向量存储
- 向量近邻搜索
- 检索相关字段

### 这样设计的原因

- 关系型数据库更适合事务、一致性和后台管理查询
- 向量数据库更适合语义检索
- 业务存储和检索存储分层更接近真实生产系统
- 也更容易在面试中解释系统边界，而不是把所有东西堆进一个库里

## 6. 系统架构

```text
Client / Demo UI
        |
        v
    FastAPI API
        |
        |---- PostgreSQL
        |       |- documents
        |       |- chunks
        |       |- tasks
        |
        |---- LanceDB
        |       |- vectors
        |       |- retrieval fields
        |
        |---- Redis
        |       |- Celery broker
        |       |- task result backend
        |       |- search cache
        |
        v
  Celery Workers
        |
        |---- ingestion worker
        |---- embedding/index worker
```

### 6.1 模块分层

- `api/`：路由层，暴露文档、任务、检索、问答接口
- `services/`：业务逻辑层，负责文档、chunk、embedding、检索、缓存、rerank 等逻辑
- `db/`：数据库连接与客户端封装
- `models/`：SQLAlchemy ORM 模型
- `schemas/`：Pydantic 请求响应结构
- `workers/`：Celery 任务定义
- `scripts/`：迁移、数据导入、评测、benchmark 等脚本

### 6.2 设计原则

1. 在线与离线解耦
   上传接口不直接等待 embedding 完成，而是快速返回并由 worker 异步处理。

2. 结构化数据与检索数据分层
   PostgreSQL 和 LanceDB 分别服务不同职责。

3. 可验证优先
   项目不仅能跑，还提供迁移、离线评测、在线 benchmark 和复现实验命令。

4. 稳定性优先于花哨功能
   去重、缓存、重试、删除清理和迁移脚手架都优先落地。

### 6.3 上传入库时序图

```text
参与者：用户 / API / PostgreSQL / Celery / Ingestion Worker / Embedding Worker / LanceDB / Redis

用户              API               PostgreSQL          Celery              Ingestion Worker      Embedding Worker      LanceDB          Redis
 |                 |                    |                  |                      |                     |                  |               |
 |----上传文件----->|                    |                  |                      |                     |                  |               |
 |                 |--计算 content_hash--|                  |                      |                     |                  |               |
 |                 |--查询是否重复------->|                  |                      |                     |                  |               |
 |                 |<-----返回结果--------|                  |                      |                     |                  |               |
 |                 |--写入 documents----->|                  |                      |                     |                  |               |
 |                 |--写入 tasks--------->|                  |                      |                     |                  |               |
 |                 |----投递任务----------------------------->|                      |                     |                  |               |
 |<---返回文档ID/任务ID--|                |                  |                      |                     |                  |               |
 |                 |                    |                  |----分发任务---------->|                     |                  |               |
 |                 |                    |                  |                      |--解析文档/切块------>|                  |               |
 |                 |                    |<--写入 chunks-----|                      |                     |                  |               |
 |                 |                    |                  |<---投递索引任务------|                     |                  |               |
 |                 |                    |                  |--------------------->|                     |                  |               |
 |                 |                    |                  |                      |                     |--读取 chunks---->|               |
 |                 |                    |                  |                      |                     |--生成 embedding--|               |
 |                 |                    |                  |                      |                     |----写入向量------>|               |
 |                 |                    |<--更新状态--------|                      |                     |                  |               |
 |                 |                    |                  |                      |                     |------清缓存------------------------->|
```

### 6.4 搜索问答时序图

```text
参与者：用户 / API / Redis / PostgreSQL / LanceDB / Rerank / LLM Service

用户              API                Redis            PostgreSQL          LanceDB            Rerank            LLM Service
 |                 |                   |                   |                  |                  |                  |
 |----发起 search/chat->|              |                   |                  |                  |                  |
 |                 |----检查缓存------>|                   |                  |                  |                  |
 |                 |<---命中/未命中----|                   |                  |                  |                  |
 |                 |---若未命中，读取过滤条件->|             |                  |                  |                  |
 |                 |<------返回元数据------------|          |                  |                  |                  |
 |                 |--------向量检索----------------------------------------->|                  |                  |
 |                 |<---------------------------返回候选结果-------------------|                  |                  |
 |                 |---若 lexical/hybrid，执行词法检索---->|                  |                  |                  |
 |                 |<------------返回 chunk 候选------------|                  |                  |                  |
 |                 |-------------------融合/重排----------------------------------------------->|                  |
 |                 |<--------------------------------------返回排序结果---------------------------|                  |
 |                 |----写入缓存------>|                   |                  |                  |                  |
 |                 |---若为 chat，请求最终回答--------------------------------------------------------------->|
 |                 |<--------------------------------------------------------返回 grounded answer-----------|
 |<----返回检索结果或问答----|          |                   |                  |                  |                  |
```

## 7. 目录结构

```text
rag-platform/
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── workers/
│   ├── static/
│   └── main.py
├── alembic/
├── scripts/
├── tests/
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
├── README.md
└── ms.md
```

## 8. 数据模型设计

### 8.1 `documents`

用于存储上传文档的元数据，核心字段包括：

- `id`
- `filename`
- `content_type`
- `storage_path`
- `file_size`
- `content_hash`
- `knowledge_base`
- `status`
- `created_at`
- `updated_at`

这个表的作用是支撑：

- 文档管理
- 去重判断
- 状态展示
- 知识库维度过滤

### 8.2 `chunks`

用于存储切块后的结构化记录，核心字段包括：

- `id`
- `document_id`
- `chunk_index`
- `content`
- `token_count`
- `char_count`
- `source`
- `status`

这个表主要用于：

- 管理切块内容
- 支持词法检索输入
- 支撑离线排查与调试

### 8.3 `tasks`

用于存储异步任务状态，核心字段包括：

- `id`
- `document_id`
- `task_type`
- `status`
- `celery_task_id`
- `error_message`
- `retry_count`
- `created_at`
- `finished_at`

这个表的作用是：

- 任务追踪
- 重试控制
- 故障排查

### 8.4 LanceDB 表

LanceDB 中主要存储：

- `chunk_id`
- `document_id`
- `knowledge_base`
- `text`
- `vector`
- `source`
- `chunk_index`

它服务于在线向量检索，而不是结构化业务查询。

## 9. 关键流程说明

### 9.1 文档上传流程

上传流程可以概括为：

1. 前端或客户端上传文件
2. API 读取内容并计算 `content_hash`
3. 判断同一知识库内是否重复上传
4. 若不重复，则保存文件并写入文档元数据
5. 创建任务记录
6. 投递 ingestion 任务
7. 返回文档 ID 与任务 ID

这个流程的关键点是：

- 用户请求快速返回
- 重计算不发生在在线接口里
- 重复内容不会重复索引

### 9.2 ingestion 流程

ingestion worker 负责：

1. 读取原始文件
2. 抽取文本内容
3. 清洗无意义空白
4. 按 `chunk_size` 和 `chunk_overlap` 切块
5. 将 chunk 写入 PostgreSQL
6. 触发 embedding/index 任务

这样做的好处是：

- 逻辑职责清晰
- 更容易做失败重试
- 后续容易扩展为批量处理

### 9.3 embedding 与索引流程

embedding/index worker 负责：

1. 读取某篇文档的所有 chunk
2. 为每个 chunk 生成 embedding
3. 写入 LanceDB
4. 更新 chunk 状态与 document 状态
5. 清理搜索缓存

项目当前支持两种 embedding 后端：

- 本地 deterministic hash embedding
- `sentence-transformers` 模型后端

前者便于快速复现，后者便于后续升级真实效果。

### 9.4 在线搜索流程

在线搜索流程：

1. 接收 query 与搜索参数
2. 根据查询参数构造缓存 key
3. 若命中缓存，则直接返回
4. 若未命中缓存，则按检索模式执行搜索
5. 可选执行 rerank
6. 返回结果并写入缓存

这个流程体现的是工程意识，而不是只做“能搜到”。

### 9.5 问答流程

问答流程：

1. 接收 query
2. 先走检索流程得到候选 chunk
3. 将候选结果交给 `llm_service`
4. 返回 grounded answer 和 citations

当前 `llm_service` 采用 grounded summary 风格实现，便于在不依赖外部付费 API 的情况下复现整条链路。

## 10. 检索模式设计

### 10.1 `vector`

使用 embedding 后的向量进行近邻搜索。

优点：

- 语义理解能力较强
- 适合表达方式差异较大的问题

缺点：

- 对精确术语、字段名、接口名不一定稳定

### 10.2 `lexical`

使用 BM25 风格词法评分检索。

优点：

- 对关键词、术语、代码标识符更敏感
- 对工程文档、接口说明更稳

缺点：

- 对同义表达和语义近似不如向量检索

### 10.3 `hybrid`

融合 `vector` 与 `lexical` 两路结果，当前使用 RRF。

为什么用 RRF：

- 不要求不同检索器的分数在同一量纲
- 比简单加权平均更稳健
- 对排序结果融合更自然

在面试里，这一块非常适合解释“为什么技术文档场景下不能只做向量检索”。

## 11. 稳定性与工程化设计

### 11.1 内容去重

通过 `content_hash + knowledge_base` 识别重复文档，避免：

- 重复切块
- 重复 embedding
- 重复向量入库

### 11.2 搜索缓存

对 query 结果进行 Redis 缓存，降低热门查询重复计算开销。

### 11.3 缓存失效

在重新 ingestion / indexing 或文档删除后清理搜索缓存，避免脏数据。

### 11.4 任务重试

通过 `retry_count` 和显式 retry API 支持失败任务恢复。

### 11.5 删除一致性

删除文档时不仅删除 PostgreSQL 文档记录，还同步删除 LanceDB 中对应向量，并清理缓存。

## 12. 演示页面说明

根路径 `/` 对应一个轻量前端，用于演示整个系统，而不是依赖 Postman。

页面支持：

- 上传文档
- 指定知识库
- 查看 dashboard summary
- 列出当前文档
- 选择检索模式
- 直接调用 `/search` 和 `/chat`

这有两个作用：

- 方便面试时现场展示
- 让项目看起来更像内部工具，而不只是 API 样板

## 13. 主要接口

### 13.1 文档管理

- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/dashboard/summary`
- `GET /api/v1/documents/{document_id}`
- `DELETE /api/v1/documents/{document_id}`

### 13.2 任务管理

- `GET /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/retry`

### 13.3 检索与问答

- `POST /api/v1/search`
- `POST /api/v1/chat`

### 13.4 观测与页面

- `GET /metrics`
- `GET /`

## 14. 接口示例

### 14.1 上传文档

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents/upload \
  -F "file=@./README.md" \
  -F "knowledge_base=demo"
```

### 14.2 搜索

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

### 14.3 问答

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "这个系统为什么要把上传和索引构建解耦？",
    "top_k": 5,
    "knowledge_base": "demo",
    "search_mode": "hybrid",
    "use_rerank": true
  }'
```

## 15. 运行方式

### 15.1 轻量本地模式

默认配置下，项目可以使用本地 SQLite 快速启动，适合开发和功能调试。

### 15.2 PostgreSQL 工程验证模式

用于更真实的元数据管理与迁移验证，适合项目展示和答辩。

### 15.3 Docker Compose 模式

通过 `docker-compose.yml` 统一启动 API、worker、PostgreSQL 和 Redis，更接近完整服务部署。

## 16. PostgreSQL 验证结果

本项目已经在 PostgreSQL 路径下完成一轮完整验证，连接串形式如下：

```bash
DATABASE_URL=postgresql+psycopg://<db_user>:<db_password>@localhost:5432/<db_name>
```

验证结果：

- Alembic 成功迁移到 `20260401_0002`
- demo 数据导入成功，插入 `3` 条文档和 `3` 条 chunk
- 离线评测结果如下

```text
mode=vector  hit@1=1.00  hit@3=1.00
mode=lexical hit@1=1.00  hit@3=1.00
mode=hybrid  hit@1=1.00  hit@3=1.00
```

- 在线 benchmark 结果如下

```text
mode=vector  requests=20 avg=0.0013s p95=0.0019s
mode=lexical requests=20 avg=0.0013s p95=0.0016s
mode=hybrid  requests=20 avg=0.0013s p95=0.0014s
```

### 16.1 如何解读这些结果

- 在当前 demo 语料规模下，三种检索模式都能正确命中目标结果，说明链路是通的。
- `hybrid` 模式在保持准确率的同时，没有带来明显的延迟回归。
- 这说明当前系统已经具备“能验证、能解释、能扩展”的基础，而不是只停留在接口层面。

## 17. 复现实验命令

### 17.1 准备环境变量

```bash
cd rag-platform

export DATABASE_URL=postgresql+psycopg://<db_user>:<db_password>@localhost:5432/<db_name>
export DATA_DIR=./data
export UPLOAD_DIR=./data/uploads_pg
export LANCEDB_URI=./data/lancedb_pg
export PYTHONPATH=.

mkdir -p "$DATA_DIR" "$UPLOAD_DIR" "$LANCEDB_URI"
```

### 17.2 执行迁移与数据导入

```bash
conda run -n LanceDB alembic upgrade head
conda run -n LanceDB python scripts/load_demo_docs.py
```

### 17.3 离线评测

```bash
conda run -n LanceDB python scripts/evaluate_retrieval.py
```

### 17.4 启动服务

```bash
conda run -n LanceDB uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 17.5 另一终端执行 benchmark

```bash
cd rag-platform

export DATABASE_URL=postgresql+psycopg://<db_user>:<db_password>@localhost:5432/<db_name>
export DATA_DIR=./data
export UPLOAD_DIR=./data/uploads_pg
export LANCEDB_URI=./data/lancedb_pg
export PYTHONPATH=.

conda run -n LanceDB python scripts/benchmark.py
```

如果你的本机配置了代理，并且访问 `127.0.0.1` 时出现异常，可以在执行 `uvicorn` 或 `benchmark.py` 前临时清空代理环境变量。

## 18. 项目亮点总结

- 不是单纯调用大模型接口，而是实现了完整的 RAG 工程链路
- 不是只在 SQLite demo 上跑通，而是完成了 PostgreSQL 路径验证
- 不是只有向量搜索，还实现了词法检索和混合检索
- 不是只做功能，还补齐了迁移、评测、benchmark、去重、缓存和重试
- 不是只有 API，还提供了可演示页面和复现实验命令

## 19. 适合面试时强调的点

你可以从下面几个角度讲这个项目：

1. 分层设计
   说明为什么 PostgreSQL 和 LanceDB 要分层，为什么在线与离线路径要解耦。

2. 检索策略
   解释 `vector`、`lexical`、`hybrid` 的适用场景，以及为什么在技术语料中 `hybrid` 更有价值。

3. 稳定性设计
   解释为什么要做去重、缓存失效、任务重试和删除一致性。

4. 验证闭环
   强调不是只写了接口，而是有迁移、评测和 benchmark 支撑。

## 20. 后续可扩展方向

- 接入真实 embedding 模型并做效果对比
- 接入更成熟的 BM25 / 全文检索组件
- 增加多租户知识库和权限控制
- 增加批量上传与批量索引构建
- 增加更真实的数据集和检索评测指标
- 增加监控图表、限流和压测报告
