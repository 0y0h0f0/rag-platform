# RAG Platform API 参考文档

> 基础地址: `http://localhost:8000`
>
> API 前缀: `/api/v1`

---

## 目录

- [文档管理](#文档管理)
  - [上传文档](#上传文档)
  - [文档列表](#文档列表)
  - [仪表盘统计](#仪表盘统计)
  - [文档详情](#文档详情)
  - [删除文档](#删除文档)
- [检索与问答](#检索与问答)
  - [语义检索](#语义检索)
  - [RAG 对话](#rag-对话)
- [任务管理](#任务管理)
  - [查询任务状态](#查询任务状态)
  - [重试失败任务](#重试失败任务)
- [AI Infra 管理](#ai-infra-管理)
  - [已加载模型列表](#已加载模型列表)
  - [模型健康检查](#模型健康检查)
  - [更新 A/B 测试配置](#更新-ab-测试配置)
  - [A/B 测试统计](#ab-测试统计)
  - [模型指标概览](#模型指标概览)
- [系统端点](#系统端点)
  - [存活探针](#存活探针)
  - [就绪探针](#就绪探针)
  - [Prometheus 指标](#prometheus-指标)
  - [演示页面](#演示页面)
- [错误响应](#错误响应)

---

## 文档管理

### 上传文档

上传文件到 RAG 平台。系统会自动进行分块、嵌入并索引到 LanceDB。支持的文件类型: `.txt`, `.md`, `.pdf`, `.py`, `.rs`。系统通过 SHA256 内容哈希进行去重。

- **方法:** `POST`
- **路径:** `/api/v1/documents/upload`
- **Content-Type:** `multipart/form-data`
- **状态码:** `202 Accepted`

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 上传的文件，支持 `.txt`, `.md`, `.pdf`, `.py`, `.rs` |
| `knowledge_base` | string | 否 | 知识库名称，默认为 `"default"` |

#### 响应体

| 字段 | 类型 | 说明 |
|------|------|------|
| `document_id` | string | 文档唯一标识 |
| `task_id` | string | 异步任务唯一标识 |
| `status` | string | 状态，`"queued"` 或 `"deduplicated"` |
| `deduplicated` | boolean | 是否为重复文档，默认 `false` |

#### 示例请求

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@./深度学习入门.pdf" \
  -F "knowledge_base=机器学习"
```

#### 示例响应

```json
{
  "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "task_id": "e5f6a7b8-1234-5678-9012-abcdef012345",
  "status": "queued",
  "deduplicated": false
}
```

重复文档响应:

```json
{
  "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "task_id": "f9e8d7c6-5432-1098-7654-fedcba987654",
  "status": "deduplicated",
  "deduplicated": true
}
```

---

### 文档列表

获取系统中所有已上传文档的列表。

- **方法:** `GET`
- **路径:** `/api/v1/documents`

#### 响应体

返回 `DocumentRead` 对象数组:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 文档唯一标识 |
| `filename` | string | 文件名 |
| `content_type` | string \| null | MIME 类型 |
| `file_size` | integer | 文件大小（字节） |
| `knowledge_base` | string | 所属知识库 |
| `status` | string | 文档状态（如 `"indexed"`, `"processing"`, `"failed"`） |
| `created_at` | string (datetime) | 创建时间 |
| `updated_at` | string (datetime) | 更新时间 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/documents
```

#### 示例响应

```json
[
  {
    "id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
    "filename": "深度学习入门.pdf",
    "content_type": "application/pdf",
    "file_size": 1048576,
    "knowledge_base": "机器学习",
    "status": "indexed",
    "created_at": "2026-04-01T10:30:00",
    "updated_at": "2026-04-01T10:31:15"
  },
  {
    "id": "b2c3d4e5-6789-01ab-cdef-234567890abc",
    "filename": "RAG技术综述.md",
    "content_type": "text/markdown",
    "file_size": 25600,
    "knowledge_base": "default",
    "status": "indexed",
    "created_at": "2026-04-01T09:15:00",
    "updated_at": "2026-04-01T09:15:45"
  }
]
```

---

### 仪表盘统计

获取平台整体统计概览，包括文档总数、分块总数、任务状态等。

- **方法:** `GET`
- **路径:** `/api/v1/documents/dashboard/summary`

#### 响应体

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_documents` | integer | 文档总数 |
| `indexed_documents` | integer | 已索引文档数 |
| `failed_documents` | integer | 索引失败的文档数 |
| `total_tasks` | integer | 任务总数 |
| `failed_tasks` | integer | 失败任务数 |
| `total_chunks` | integer | 文本分块总数 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/documents/dashboard/summary
```

#### 示例响应

```json
{
  "total_documents": 42,
  "indexed_documents": 38,
  "failed_documents": 2,
  "total_tasks": 50,
  "failed_tasks": 3,
  "total_chunks": 1560
}
```

---

### 文档详情

根据文档 ID 获取单个文档的详细信息。

- **方法:** `GET`
- **路径:** `/api/v1/documents/{document_id}`

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `document_id` | string | 文档唯一标识 |

#### 响应体

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 文档唯一标识 |
| `filename` | string | 文件名 |
| `content_type` | string \| null | MIME 类型 |
| `file_size` | integer | 文件大小（字节） |
| `content_hash` | string | SHA256 内容哈希 |
| `knowledge_base` | string | 所属知识库 |
| `storage_path` | string | 文件存储路径 |
| `status` | string | 文档状态 |
| `created_at` | string (datetime) | 创建时间 |
| `updated_at` | string (datetime) | 更新时间 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/documents/a1b2c3d4-5678-90ab-cdef-1234567890ab
```

#### 示例响应

```json
{
  "id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "filename": "深度学习入门.pdf",
  "content_type": "application/pdf",
  "file_size": 1048576,
  "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "knowledge_base": "机器学习",
  "storage_path": "./data/uploads/abc123def456.pdf",
  "status": "indexed",
  "created_at": "2026-04-01T10:30:00",
  "updated_at": "2026-04-01T10:31:15"
}
```

#### 错误响应

```json
// 404 Not Found
{
  "detail": "document not found"
}
```

---

### 删除文档

删除指定文档及其关联数据。该操作会同时清除 PostgreSQL 中的文档和分块记录、LanceDB 中的向量索引以及 Redis 缓存。

- **方法:** `DELETE`
- **路径:** `/api/v1/documents/{document_id}`
- **状态码:** `204 No Content`

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `document_id` | string | 文档唯一标识 |

#### 示例请求

```bash
curl -X DELETE http://localhost:8000/api/v1/documents/a1b2c3d4-5678-90ab-cdef-1234567890ab
```

#### 响应

成功时返回 HTTP 204，无响应体。

#### 错误响应

```json
// 404 Not Found
{
  "detail": "document not found"
}
```

---

## 检索与问答

### 语义检索

对已索引的文档执行检索。支持向量检索、词法检索（BM25）和混合检索（RRF 融合）三种模式。

- **方法:** `POST`
- **路径:** `/api/v1/search`
- **Content-Type:** `application/json`

#### 请求体 (SearchRequest)

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | - | 查询文本，最少 1 个字符 |
| `top_k` | integer | 否 | `5` | 返回结果数量，范围 1-20 |
| `document_id` | string \| null | 否 | `null` | 限定在某个文档内检索 |
| `knowledge_base` | string \| null | 否 | `null` | 限定在某个知识库内检索 |
| `use_rerank` | boolean | 否 | `true` | 是否对结果进行重排序 |
| `search_mode` | string | 否 | `"vector"` | 检索模式: `"vector"`, `"hybrid"`, `"lexical"` |

#### 响应体 (SearchResponse)

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | string | 原始查询文本 |
| `hits` | array[SearchHit] | 检索结果列表 |

**SearchHit 对象:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_id` | string | 分块唯一标识 |
| `document_id` | string | 所属文档 ID |
| `text` | string | 分块文本内容 |
| `source` | string | 来源文件名 |
| `chunk_index` | integer | 分块在文档中的序号 |
| `score` | float | 相关性得分 |

#### 示例请求

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是注意力机制",
    "top_k": 3,
    "search_mode": "hybrid",
    "knowledge_base": "机器学习"
  }'
```

#### 示例响应

```json
{
  "query": "什么是注意力机制",
  "hits": [
    {
      "chunk_id": "chunk-001-abc",
      "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
      "text": "注意力机制（Attention Mechanism）是深度学习中的一种重要技术，最初应用于机器翻译领域。其核心思想是让模型在处理输入序列时，能够动态地关注与当前任务最相关的部分，而非平等对待所有输入。",
      "source": "深度学习入门.pdf",
      "chunk_index": 12,
      "score": 0.9235
    },
    {
      "chunk_id": "chunk-002-def",
      "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
      "text": "自注意力机制（Self-Attention）是 Transformer 架构的核心组件。它通过计算查询（Query）、键（Key）和值（Value）三个向量之间的关系来捕获序列内部的依赖关系。",
      "source": "深度学习入门.pdf",
      "chunk_index": 13,
      "score": 0.8871
    },
    {
      "chunk_id": "chunk-003-ghi",
      "document_id": "b2c3d4e5-6789-01ab-cdef-234567890abc",
      "text": "多头注意力（Multi-Head Attention）将输入投影到多个子空间中分别计算注意力，再将结果拼接。这种方式使模型能够同时关注来自不同位置、不同表示子空间的信息。",
      "source": "RAG技术综述.md",
      "chunk_index": 5,
      "score": 0.8456
    }
  ]
}
```

---

### RAG 对话

基于检索增强生成（RAG）的对话接口。系统首先检索相关文档片段，然后调用 LLM（DeepSeek）生成基于上下文的回答。

- **方法:** `POST`
- **路径:** `/api/v1/chat`
- **Content-Type:** `application/json`

#### 请求体 (ChatRequest)

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | - | 问题文本，最少 1 个字符 |
| `top_k` | integer | 否 | `5` | 检索结果数量，范围 1-20 |
| `document_id` | string \| null | 否 | `null` | 限定在某个文档内检索 |
| `knowledge_base` | string \| null | 否 | `null` | 限定在某个知识库内检索 |
| `use_rerank` | boolean | 否 | `true` | 是否对检索结果进行重排序 |
| `search_mode` | string | 否 | `"vector"` | 检索模式: `"vector"`, `"hybrid"`, `"lexical"` |

#### 响应体 (ChatResponse)

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | string | 原始问题文本 |
| `answer` | string | LLM 生成的回答 |
| `citations` | array[SearchHit] | 引用的文档片段列表 |
| `model_version` | string \| null | 使用的模型版本信息 |

#### 示例请求

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Transformer 模型的核心创新是什么？",
    "top_k": 3,
    "search_mode": "hybrid",
    "use_rerank": true
  }'
```

#### 示例响应

```json
{
  "query": "Transformer 模型的核心创新是什么？",
  "answer": "Transformer 模型的核心创新在于完全基于自注意力机制（Self-Attention）来处理序列数据，摒弃了传统的循环神经网络（RNN）和卷积神经网络（CNN）结构。其关键创新点包括：\n\n1. **自注意力机制**：通过 Query-Key-Value 的计算方式，让模型能够直接捕获序列中任意两个位置之间的依赖关系，解决了 RNN 中长距离依赖问题。\n\n2. **多头注意力**：将注意力计算分散到多个子空间中并行执行，使模型能够同时关注不同类型的特征。\n\n3. **位置编码**：由于自注意力机制本身不包含位置信息，Transformer 引入了正弦位置编码来注入序列顺序信息。\n\n这些创新使得 Transformer 在训练效率和性能上都大幅超越了之前的序列模型。",
  "citations": [
    {
      "chunk_id": "chunk-002-def",
      "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
      "text": "自注意力机制（Self-Attention）是 Transformer 架构的核心组件。它通过计算查询（Query）、键（Key）和值（Value）三个向量之间的关系来捕获序列内部的依赖关系。",
      "source": "深度学习入门.pdf",
      "chunk_index": 13,
      "score": 0.9312
    },
    {
      "chunk_id": "chunk-003-ghi",
      "document_id": "b2c3d4e5-6789-01ab-cdef-234567890abc",
      "text": "多头注意力（Multi-Head Attention）将输入投影到多个子空间中分别计算注意力，再将结果拼接。这种方式使模型能够同时关注来自不同位置、不同表示子空间的信息。",
      "source": "RAG技术综述.md",
      "chunk_index": 5,
      "score": 0.8975
    },
    {
      "chunk_id": "chunk-004-jkl",
      "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
      "text": "Transformer 采用编码器-解码器架构，其中编码器由多层自注意力和前馈网络组成，解码器则额外包含交叉注意力层以关注编码器的输出。",
      "source": "深度学习入门.pdf",
      "chunk_index": 14,
      "score": 0.8643
    }
  ],
  "model_version": "deepseek-chat"
}
```

---

## 任务管理

### 查询任务状态

根据任务 ID 查询异步任务的执行状态。任务类型包括文档解析和嵌入索引。

- **方法:** `GET`
- **路径:** `/api/v1/tasks/{task_id}`

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务唯一标识 |

#### 响应体 (TaskRead)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务唯一标识 |
| `document_id` | string \| null | 关联的文档 ID |
| `task_type` | string | 任务类型（如 `"ingest_and_index"`） |
| `status` | string | 任务状态: `"queued"`, `"processing"`, `"completed"`, `"failed"` |
| `celery_task_id` | string \| null | Celery 任务 ID |
| `error_message` | string \| null | 失败时的错误信息 |
| `retry_count` | integer | 重试次数 |
| `created_at` | string (datetime) | 创建时间 |
| `finished_at` | string (datetime) \| null | 完成时间 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/tasks/e5f6a7b8-1234-5678-9012-abcdef012345
```

#### 示例响应

任务进行中:

```json
{
  "id": "e5f6a7b8-1234-5678-9012-abcdef012345",
  "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "task_type": "ingest_and_index",
  "status": "processing",
  "celery_task_id": "c8d9e0f1-abcd-1234-5678-9876543210ab",
  "error_message": null,
  "retry_count": 0,
  "created_at": "2026-04-01T10:30:00",
  "finished_at": null
}
```

任务完成:

```json
{
  "id": "e5f6a7b8-1234-5678-9012-abcdef012345",
  "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "task_type": "ingest_and_index",
  "status": "completed",
  "celery_task_id": "c8d9e0f1-abcd-1234-5678-9876543210ab",
  "error_message": null,
  "retry_count": 0,
  "created_at": "2026-04-01T10:30:00",
  "finished_at": "2026-04-01T10:31:15"
}
```

#### 错误响应

```json
// 404 Not Found
{
  "detail": "task not found"
}
```

---

### 重试失败任务

重新触发一个失败的异步任务。仅适用于关联了文档的任务。

- **方法:** `POST`
- **路径:** `/api/v1/tasks/{task_id}/retry`
- **状态码:** `202 Accepted`

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务唯一标识 |

#### 响应体

返回更新后的 `TaskRead` 对象（字段同上）。

#### 示例请求

```bash
curl -X POST http://localhost:8000/api/v1/tasks/e5f6a7b8-1234-5678-9012-abcdef012345/retry
```

#### 示例响应

```json
{
  "id": "e5f6a7b8-1234-5678-9012-abcdef012345",
  "document_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "task_type": "ingest_and_index",
  "status": "queued",
  "celery_task_id": "d0e1f2a3-bcde-2345-6789-0123456789ab",
  "error_message": null,
  "retry_count": 1,
  "created_at": "2026-04-01T10:30:00",
  "finished_at": null
}
```

#### 错误响应

```json
// 404 Not Found
{
  "detail": "task not found"
}

// 400 Bad Request
{
  "detail": "task is not associated with a document"
}
```

---

## AI Infra 管理

### 已加载模型列表

获取当前已注册并加载的所有模型信息。

- **方法:** `GET`
- **路径:** `/api/v1/infra/models`

#### 响应体 (ModelsResponse)

| 字段 | 类型 | 说明 |
|------|------|------|
| `models` | array[ModelInfo] | 模型信息列表 |

**ModelInfo 对象:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `provider` | string | 模型提供商（如 `"deepseek"`, `"ollama"`） |
| `model` | string | 模型名称 |
| `type` | string | 模型类型（如 `"llm"`, `"embedding"`） |
| `role` | string \| null | 模型角色（如 `"primary"`, `"fallback"`） |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/infra/models
```

#### 示例响应

```json
{
  "models": [
    {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "type": "llm",
      "role": "primary"
    },
    {
      "provider": "sentence-transformers",
      "model": "all-MiniLM-L6-v2",
      "type": "embedding",
      "role": "primary"
    }
  ]
}
```

---

### 模型健康检查

检查所有已注册模型的健康状态，并更新 Prometheus 指标。

- **方法:** `GET`
- **路径:** `/api/v1/infra/models/health`

#### 响应体 (HealthResponse)

| 字段 | 类型 | 说明 |
|------|------|------|
| `results` | object | 键为 `"provider/model"`，值为布尔健康状态 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/infra/models/health
```

#### 示例响应

```json
{
  "results": {
    "deepseek/deepseek-chat": true,
    "sentence-transformers/all-MiniLM-L6-v2": true
  }
}
```

---

### 更新 A/B 测试配置

动态调整 A/B 测试中两个 LLM 模型之间的流量分配比例。

- **方法:** `POST`
- **路径:** `/api/v1/infra/ab/config`
- **Content-Type:** `application/json`

#### 请求体 (ABConfigRequest)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `traffic_split` | float | 是 | 流量分配比例（0.0-1.0），表示分配给模型 A 的流量比例 |

#### 响应体 (ABConfigResponse)

| 字段 | 类型 | 说明 |
|------|------|------|
| `traffic_split` | float | 当前流量分配比例 |
| `model_a` | string | 模型 A 名称 |
| `model_b` | string | 模型 B 名称 |

#### 示例请求

```bash
curl -X POST http://localhost:8000/api/v1/infra/ab/config \
  -H "Content-Type: application/json" \
  -d '{"traffic_split": 0.7}'
```

#### 示例响应

```json
{
  "traffic_split": 0.7,
  "model_a": "deepseek-chat",
  "model_b": "deepseek-coder"
}
```

未启用 A/B 测试时的响应:

```json
{
  "traffic_split": 1.0,
  "model_a": "N/A",
  "model_b": "N/A"
}
```

---

### A/B 测试统计

获取 A/B 测试的详细统计数据，包括各模型的请求数、平均延迟和平均 Token 用量。

- **方法:** `GET`
- **路径:** `/api/v1/infra/ab/stats`

#### 响应体 (ABStatsResponse)

| 字段 | 类型 | 说明 |
|------|------|------|
| `stats` | object | 键为模型名称，值为统计对象 |
| `traffic_split` | float | 当前流量分配比例 |

**统计对象字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `requests` | integer | 总请求数 |
| `avg_latency` | float | 平均延迟（秒） |
| `avg_tokens` | float | 平均 Token 用量 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/infra/ab/stats
```

#### 示例响应

```json
{
  "stats": {
    "deepseek-chat": {
      "requests": 350,
      "avg_latency": 1.23,
      "avg_tokens": 256.5
    },
    "deepseek-coder": {
      "requests": 150,
      "avg_latency": 1.45,
      "avg_tokens": 312.8
    }
  },
  "traffic_split": 0.7
}
```

未启用 A/B 测试时的响应:

```json
{
  "stats": {},
  "traffic_split": 1.0
}
```

---

### 模型指标概览

获取所有模型的信息列表和健康状态的综合视图。

- **方法:** `GET`
- **路径:** `/api/v1/infra/metrics/models`

#### 响应体 (ModelMetricsSummary)

| 字段 | 类型 | 说明 |
|------|------|------|
| `models` | array[ModelInfo] | 模型信息列表 |
| `health` | object | 键为 `"provider/model"`，值为布尔健康状态 |

#### 示例请求

```bash
curl http://localhost:8000/api/v1/infra/metrics/models
```

#### 示例响应

```json
{
  "models": [
    {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "type": "llm",
      "role": "primary"
    },
    {
      "provider": "sentence-transformers",
      "model": "all-MiniLM-L6-v2",
      "type": "embedding",
      "role": "primary"
    }
  ],
  "health": {
    "deepseek/deepseek-chat": true,
    "sentence-transformers/all-MiniLM-L6-v2": true
  }
}
```

---

## 系统端点

### 存活探针

Kubernetes 存活探针端点。用于判断应用进程是否存活。

- **方法:** `GET`
- **路径:** `/health`

#### 示例请求

```bash
curl http://localhost:8000/health
```

#### 示例响应

```json
{
  "status": "ok"
}
```

---

### 就绪探针

Kubernetes 就绪探针端点。深度检查数据库、Redis 和模型服务的可用性。

- **方法:** `GET`
- **路径:** `/health/ready`
- **状态码:** 全部健康时返回 `200`，任一不健康时返回 `503`

#### 响应体

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"ready"` 或 `"not_ready"` |
| `checks` | object | 各组件健康状态，键为组件名，值为布尔值 |

#### 示例请求

```bash
curl http://localhost:8000/health/ready
```

#### 示例响应 (全部健康, HTTP 200)

```json
{
  "status": "ready",
  "checks": {
    "database": true,
    "redis": true,
    "deepseek/deepseek-chat": true,
    "sentence-transformers/all-MiniLM-L6-v2": true
  }
}
```

#### 示例响应 (部分不健康, HTTP 503)

```json
{
  "status": "not_ready",
  "checks": {
    "database": true,
    "redis": false,
    "deepseek/deepseek-chat": true,
    "sentence-transformers/all-MiniLM-L6-v2": true
  }
}
```

---

### Prometheus 指标

以 Prometheus 文本格式暴露应用指标，供监控系统抓取。

- **方法:** `GET`
- **路径:** `/metrics`
- **Content-Type:** `text/plain`

#### 示例请求

```bash
curl http://localhost:8000/metrics
```

#### 示例响应

```text
# HELP document_uploads_total Total number of document uploads
# TYPE document_uploads_total counter
document_uploads_total 42.0
# HELP deduplicated_uploads_total Total number of deduplicated uploads
# TYPE deduplicated_uploads_total counter
deduplicated_uploads_total 5.0
# HELP search_requests_total Total number of search requests
# TYPE search_requests_total counter
search_requests_total 128.0
# HELP search_latency_seconds Search request latency
# TYPE search_latency_seconds histogram
search_latency_seconds_bucket{le="0.1"} 45.0
search_latency_seconds_bucket{le="0.5"} 110.0
search_latency_seconds_bucket{le="1.0"} 125.0
search_latency_seconds_bucket{le="+Inf"} 128.0
search_latency_seconds_count 128.0
search_latency_seconds_sum 38.5
```

---

### 演示页面

返回内置的前端演示页面（HTML）。

- **方法:** `GET`
- **路径:** `/`
- **Content-Type:** `text/html`

#### 示例请求

```bash
curl http://localhost:8000/
```

在浏览器中直接访问 `http://localhost:8000/` 即可查看演示界面。

---

## 错误响应

所有 API 端点在出错时返回统一的 JSON 错误格式:

```json
{
  "detail": "错误描述信息"
}
```

### HTTP 状态码

| 状态码 | 说明 | 常见场景 |
|--------|------|----------|
| `400` | 请求错误 | 请求参数校验失败、不支持的文件类型、任务未关联文档 |
| `404` | 资源未找到 | 文档 ID 或任务 ID 不存在 |
| `422` | 请求体校验失败 | JSON 格式错误、必填字段缺失、字段值超出范围 |
| `429` | 请求频率超限 | 超出速率限制（由 RateLimitMiddleware 控制） |
| `500` | 服务器内部错误 | 服务端未预期的异常 |
| `503` | 服务不可用 | 就绪探针检测到依赖服务不健康 |

### 422 校验错误示例

当请求体不满足 Pydantic 模型约束时，FastAPI 自动返回详细的校验错误:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "query"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": {"min_length": 1}
    }
  ]
}
```

### 429 限流错误示例

```json
{
  "detail": "Rate limit exceeded"
}
```
