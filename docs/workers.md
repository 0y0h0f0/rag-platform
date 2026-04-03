# RAG Platform 异步任务技术文档

> 详细解析 Celery 异步任务流水线，包括配置、入库流程、向量化流程和错误处理。

---

## 目录

1. [为什么需要异步任务](#1-为什么需要异步任务)
2. [Celery 配置](#2-celery-配置)
3. [任务流水线](#3-任务流水线)
4. [ingest_document 任务](#4-ingest_document-任务)
5. [embed_document 任务](#5-embed_document-任务)
6. [错误处理与重试](#6-错误处理与重试)
7. [开发模式 (EAGER)](#7-开发模式-eager)
8. [生产环境运行](#8-生产环境运行)

---

## 1. 为什么需要异步任务

文档入库涉及多个耗时步骤：

| 步骤 | 耗时 | 原因 |
|------|------|------|
| 文本提取 | 100ms-5s | PDF 解析可能很慢 |
| 分块 | 10-100ms | 滑动窗口计算 |
| 向量化 | 1-30s | 每个 chunk 都要调用模型推理 |
| 写入 LanceDB | 50-500ms | 磁盘 I/O |

如果同步执行，上传一个 100 页 PDF 可能需要等待 30 秒以上。使用异步任务后：

```
用户上传 → API 返回 202 (< 100ms) → 后台处理 → 完成后更新状态
```

用户可以通过 `/tasks/{task_id}` 轮询任务状态。

---

## 2. Celery 配置

**文件：** `app/workers/celery_app.py`

```python
from celery import Celery
from app.core.config import settings

celery_app = Celery("rag_platform")

celery_app.conf.update(
    broker_url=settings.celery_broker_url,           # Redis 作为消息队列
    result_backend=settings.celery_result_backend,    # Redis 存储结果
    task_always_eager=settings.celery_task_always_eager,  # 开发模式同步执行
    task_serializer="json",                           # 任务参数序列化格式
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)

celery_app.autodiscover_tasks(["app.workers"])  # 自动发现任务模块
```

**关键配置项：**

| 配置 | 值 | 说明 |
|------|----|------|
| `broker_url` | `redis://localhost:6379/0` | 任务消息存放位置 |
| `result_backend` | `redis://localhost:6379/1` | 任务结果存放位置 |
| `task_always_eager` | `true`(dev)/`false`(prod) | 同步/异步模式切换 |
| `task_serializer` | `json` | 参数序列化为 JSON |
| `timezone` | `UTC` | 统一时区 |

---

## 3. 任务流水线

```
文档上传 API (routes_docs.py)
     │
     │ 1. 保存文件到磁盘
     │ 2. 创建 Document 记录 (PG)
     │ 3. 创建 Task 记录 (PG)
     │ 4. 发送 Celery 任务
     │
     ▼
ingest_document (ingestion_tasks.py)
     │
     │ 1. 更新状态: processing
     │ 2. 提取文本 (PDF/TXT/MD)
     │ 3. 滑动窗口分块
     │ 4. 存储 Chunks 到 PG
     │ 5. 清除搜索缓存
     │ 6. 触发下游任务
     │
     ▼
embed_document (embedding_tasks.py)
     │
     │ 1. 从 PG 读取 Chunks
     │ 2. 对每个 Chunk 向量化
     │ 3. 批量写入 LanceDB
     │ 4. 更新 Chunk 状态: indexed
     │ 5. 更新 Document 状态: indexed
     │ 6. 更新 Task 状态: completed
     │ 7. 清除搜索缓存
     │
     ▼
完成 ✓
```

**为什么拆成两个任务而非一个：**

1. **关注点分离**：入库（CPU 密集）和向量化（GPU/网络密集）可以部署在不同的 Worker 上
2. **独立重试**：如果向量化失败（如 Ollama 超时），不需要重做文本提取和分块
3. **可观测性**：在 Jaeger 中可以分别看到两个阶段的耗时

---

## 4. ingest_document 任务

**文件：** `app/workers/ingestion_tasks.py`

```python
@celery_app.task(name="ingest_document")
def ingest_document(document_id: str, file_path: str, task_id: str):
```

### 4.1 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `document_id` | str | 文档 UUID |
| `file_path` | str | 文件在磁盘上的路径 |
| `task_id` | str | 任务 UUID（用于状态更新） |

### 4.2 执行流程

```python
def ingest_document(document_id, file_path, task_id):
    db = SessionLocal()
    try:
        # 1. 更新状态
        task_service.update_task(db, task_id, status="processing")
        document = db.query(Document).get(document_id)
        document.status = "processing"
        db.commit()

        # 2. 提取文本
        text = chunk_service.extract_text(file_path)

        # 3. 分块
        chunks_data = chunk_service.chunk_text(text, source=document.filename)

        # 4. 存储到 PostgreSQL
        chunks = chunk_service.replace_document_chunks(db, document_id, chunks_data)

        # 5. 清除搜索缓存（新内容入库，旧缓存失效）
        cache_service.clear_namespace("search")

        # 6. 触发向量化任务
        embed_document.delay(document_id, task_id)

        # 7. Prometheus 指标
        INGESTION_TASKS.labels(status="success").inc()

    except Exception as e:
        # 错误处理
        document.status = "failed"
        task_service.update_task(db, task_id, status="failed", error_message=str(e))
        db.commit()
        INGESTION_TASKS.labels(status="failed").inc()
        raise
    finally:
        db.close()
```

### 4.3 链路追踪集成

任务执行被包裹在 `trace_span` 中：

```python
with trace_span("celery.ingest_document", {"document_id": document_id}):
    # 任务逻辑...
```

---

## 5. embed_document 任务

**文件：** `app/workers/embedding_tasks.py`

```python
@celery_app.task(name="embed_document")
def embed_document(document_id: str, task_id: str):
```

### 5.1 执行流程

```python
def embed_document(document_id, task_id):
    db = SessionLocal()
    try:
        # 1. 读取文档的所有 Chunks
        chunks = chunk_service.get_document_chunks(db, document_id)

        if not chunks:
            # 无 Chunk 可索引
            task_service.update_task(db, task_id, status="completed")
            return

        # 2. 向量化并写入 LanceDB
        retrieval_service = RetrievalService()
        indexed_count = retrieval_service.index_chunks(db, chunks)

        # 3. 更新文档状态
        document = db.query(Document).get(document_id)
        document.status = "indexed"
        db.commit()

        # 4. 更新任务状态
        task_service.update_task(db, task_id, status="completed")

        # 5. 清除搜索缓存
        cache_service.clear_namespace("search")

    except Exception as e:
        document.status = "failed"
        task_service.update_task(db, task_id, status="failed", error_message=str(e))
        db.commit()
        raise
    finally:
        db.close()
```

### 5.2 index_chunks 内部流程

```python
# retrieval_service.py
def index_chunks(self, db, chunks):
    rows = []
    for chunk in chunks:
        vector = self.embedding_service.embed_text(chunk.content)  # 向量化
        rows.append({
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "knowledge_base": chunk.document.knowledge_base,
            "text": chunk.content,
            "vector": vector,
            "source": chunk.source,
            "chunk_index": chunk.chunk_index,
        })
        chunk.status = "indexed"  # 更新 PG 中的 chunk 状态

    self.lancedb.add_chunks(rows)  # 批量写入 LanceDB
    db.commit()
    return len(rows)
```

---

## 6. 错误处理与重试

### 6.1 错误捕获

两个任务都使用 try/except/finally 结构：
- **成功路径**：更新状态为 completed/indexed
- **失败路径**：更新状态为 failed，记录 error_message
- **finally**：确保 Session 关闭

### 6.2 手动重试

通过 `/api/v1/tasks/{task_id}/retry` 端点触发：

```python
# routes_tasks.py
@router.post("/{task_id}/retry")
def retry_task(task_id: str, db: Session = Depends(get_db)):
    task = task_service.get_task(db, task_id)
    if task.document_id is None:
        raise HTTPException(400, "task is not associated with a document")

    task_service.increment_retry(db, task_id)  # retry_count += 1, status = "queued"

    document = db.query(Document).get(task.document_id)
    ingest_document.delay(
        document.id,
        document.storage_path,
        task.id,
    )
    return task
```

### 6.3 状态流转图

```
Task 状态:
  pending → queued → processing → completed ✓
                                → failed ✗
                                    ↓
                               retry → queued (retry_count += 1)

Document 状态:
  uploaded → processing → indexed ✓
                        → failed ✗

Chunk 状态:
  pending → indexed ✓
```

---

## 7. 开发模式 (EAGER)

```ini
CELERY_TASK_ALWAYS_EAGER=true
```

当设为 `true` 时，所有 Celery 任务**同步执行**：
- `task.delay(args)` 直接在当前进程中执行，不经过 Redis
- 不需要启动 Celery Worker
- 不需要启动 Redis

**使用场景：**
- 本地开发调试
- 运行测试
- 快速验证功能

**注意事项：**
- EAGER 模式下，文档上传 API 的响应时间会包含完整的入库和向量化时间
- 不适合性能测试

---

## 8. 生产环境运行

### 8.1 启动 Worker

```bash
# 基本启动
celery -A app.workers.celery_app.celery_app worker --loglevel=info

# 指定并发数
celery -A app.workers.celery_app.celery_app worker --loglevel=info --concurrency=4

# 指定队列（如果需要分离入库和向量化任务）
celery -A app.workers.celery_app.celery_app worker --queues=ingest,embed --loglevel=info
```

### 8.2 环境变量

```ini
CELERY_TASK_ALWAYS_EAGER=false    # 必须为 false
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

### 8.3 Docker Compose 中的 Worker

```yaml
worker:
  build: .
  command: celery -A app.workers.celery_app.celery_app worker --loglevel=info
  environment:
    CELERY_TASK_ALWAYS_EAGER: "false"
  depends_on:
    - redis
    - postgres
```

### 8.4 Kubernetes 中的 Worker

```yaml
# k8s/worker-deployment.yaml
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: worker
          command:
            - celery
            - -A
            - app.workers.celery_app.celery_app
            - worker
            - --loglevel=info
```

### 8.5 监控 Worker

```bash
# 查看活跃任务
celery -A app.workers.celery_app.celery_app inspect active

# 查看预留任务
celery -A app.workers.celery_app.celery_app inspect reserved

# 查看 Worker 统计
celery -A app.workers.celery_app.celery_app inspect stats
```

### 8.6 任务状态查询

用户可以通过 API 轮询任务状态：

```bash
# 查询任务状态
curl http://localhost:8000/api/v1/tasks/{task_id}

# 响应示例
{
  "id": "...",
  "status": "processing",   // queued → processing → completed/failed
  "retry_count": 0,
  "error_message": null
}
```

典型的前端轮询策略：每 2 秒查询一次，直到 status 变为 `completed` 或 `failed`。
