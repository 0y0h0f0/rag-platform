# RAG Platform 服务层技术文档

> 详细解析 `app/services/` 下所有业务逻辑服务的设计思路、核心算法和实现细节。

---

## 目录

1. [服务层总览](#1-服务层总览)
2. [RetrievalService — 检索编排器](#2-retrievalservice--检索编排器)
3. [EmbeddingService — 向量化服务](#3-embeddingservice--向量化服务)
4. [BM25Service — 词法检索](#4-bm25service--词法检索)
5. [HybridSearchService — RRF 混合融合](#5-hybridsearchservice--rrf-混合融合)
6. [RerankService — 重排序](#6-rerankservice--重排序)
7. [ChunkService — 文本提取与分块](#7-chunkservice--文本提取与分块)
8. [LLMService — 大模型调用](#8-llmservice--大模型调用)
9. [CacheService — 缓存服务](#9-cacheservice--缓存服务)
10. [DocumentService & TaskService — 文档与任务管理](#10-documentservice--taskservice--文档与任务管理)

---

## 1. 服务层总览

服务层是平台的核心，封装了所有业务逻辑。路由层（`app/api/`）通过依赖注入获取 Service 实例，Service 之间也存在协作关系：

```
┌─────────────────────────────────────────────────────────────┐
│                     RetrievalService                        │
│                     (检索编排器 — 核心)                       │
│                                                              │
│  聚合:                                                       │
│  ├── EmbeddingService   → 查询向量化                          │
│  ├── LanceDBClient      → 向量搜索                           │
│  ├── BM25Service        → 词法搜索                           │
│  ├── HybridSearchService→ RRF 融合                           │
│  ├── ChunkService       → 获取可搜索的文本块                  │
│  └── CacheService       → 缓存检索结果                       │
├──────────────────────────────────────────────────────────────┤
│  LLMService → 基于检索结果生成回答 (调用 ProviderRegistry)    │
├──────────────────────────────────────────────────────────────┤
│  RerankService → 对检索结果重排序                             │
├──────────────────────────────────────────────────────────────┤
│  DocumentService / TaskService → 文档 CRUD / 任务状态管理     │
└──────────────────────────────────────────────────────────────┘
```

**关键设计原则：**
- 每个 Service 职责单一，通过组合实现复杂流程
- Service 之间通过构造函数组合，不使用全局变量
- 所有 Service 都是无状态的（状态在数据库/缓存中），可以安全地在多线程中使用

---

## 2. RetrievalService — 检索编排器

**文件：** `app/services/retrieval_service.py`

### 2.1 职责

RetrievalService 是整个检索链路的**编排者**，协调多个子服务完成从查询到结果的全流程。

### 2.2 架构

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

### 2.3 核心方法：`search()`

```python
def search(
    self,
    db: Session,
    query: str,
    top_k: int,
    document_id: str | None = None,
    search_mode: str = "vector",
    knowledge_base: str | None = None,
) -> list[dict]:
```

**参数说明：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `db` | SQLAlchemy Session | 数据库会话（用于 BM25 查 chunks） |
| `query` | str | 用户查询文本 |
| `top_k` | int | 返回结果数量 |
| `document_id` | str, optional | 限定在某个文档内检索 |
| `search_mode` | str | `"vector"` / `"lexical"` / `"hybrid"` |
| `knowledge_base` | str, optional | 限定在某个知识库内检索 |

**执行流程（带缓存和追踪）：**

```
search(query, mode)
  │
  ├─ 1. 构造缓存 key = SHA256({query, top_k, document_id, search_mode, kb})
  ├─ 2. 查 Redis 缓存 → 命中则直接返回
  │
  ├─ 3. trace_span("retrieval.search") 开始
  │
  ├─ 4. 根据 search_mode 分支：
  │     │
  │     ├── "lexical":
  │     │     ├── chunk_service.get_searchable_chunks(db, document_id, kb)
  │     │     └── bm25_service.score(query, chunks, top_k)
  │     │
  │     ├── "vector":
  │     │     └── _vector_search(query, top_k, document_id, kb)
  │     │         ├── embedding_service.embed_text(query) → query_vector
  │     │         ├── lancedb.search(query_vector, top_k, filters)
  │     │         └── distance → score: score = 1.0 / (1.0 + distance)
  │     │
  │     └── "hybrid":
  │           ├── _vector_search() → vector_hits
  │           ├── bm25_service.score() → lexical_hits
  │           └── hybrid_service.fuse(vector_hits, lexical_hits, top_k)
  │
  ├─ 5. 写入 Redis 缓存 (TTL = 300s)
  └─ 6. 返回 hits
```

### 2.4 向量搜索的距离-分数转换

LanceDB 返回余弦距离（cosine distance），值域为 [0, 2]。我们需要将其转换为分数（越高越好）：

```python
score = 1.0 / (1.0 + distance)
```

| 距离 (distance) | 分数 (score) | 含义 |
|-----------------|-------------|------|
| 0.0 | 1.0 | 完全相同 |
| 0.5 | 0.667 | 非常相似 |
| 1.0 | 0.5 | 中等相似 |
| 2.0 | 0.333 | 不太相似 |

**为什么用这个公式而非 `1 - distance/2`：**
- `1/(1+d)` 保证输出在 (0, 1] 区间，不会出现负值
- 对高相似度结果（低距离）的区分度更好
- 与 BM25 分数量级接近，便于 RRF 融合

### 2.5 索引方法：`index_chunks()`

```python
def index_chunks(self, db: Session, chunks: list[Chunk]) -> int:
```

被 Celery embedding_tasks 调用，完成以下步骤：
1. 对每个 Chunk 调用 `embedding_service.embed_text()` 生成向量
2. 构建 LanceDB 行数据（包含 chunk_id, document_id, knowledge_base, text, vector 等字段）
3. 调用 `lancedb.add_chunks(rows)` 批量写入
4. 更新 Chunk 状态为 `"indexed"`

---

## 3. EmbeddingService — 向量化服务

**文件：** `app/services/embedding_service.py`

### 3.1 职责

将文本转换为固定维度的浮点向量，支持三种后端。

### 3.2 后端选择逻辑

```
EMBEDDING_PROVIDER 环境变量
    │
    ├── "ollama" → 通过 ProviderRegistry 使用 OllamaEmbeddingProvider
    │              → 调用 Ollama /api/embed 端点
    │              → 模型: nomic-embed-text (768 维)
    │
    └── "legacy" → 使用本地 EmbeddingService
                   │
                   ├── EMBEDDING_BACKEND="local"
                   │   → _embed_with_local_hash()
                   │   → 确定性哈希向量（用于开发/测试）
                   │
                   └── EMBEDDING_BACKEND="sentence_transformers"
                       → _embed_with_model()
                       → 使用 HuggingFace sentence-transformers 模型
```

### 3.3 本地哈希嵌入算法

这是一种**确定性的特征哈希**（Feature Hashing）方法，用于无需 GPU 或模型的快速开发：

```python
def _embed_with_local_hash(self, text: str) -> list[float]:
    tokens = self.tokenize(text)          # 正则分词: \w+ 提取单词
    vec = [0.0] * settings.embedding_dim  # 初始化零向量

    for token in tokens:
        h = hashlib.md5(token.encode()).hexdigest()
        idx = int(h, 16) % settings.embedding_dim  # 映射到维度索引
        vec[idx] += 1.0                             # 累加

    # L2 归一化
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec
```

**工作原理：**
1. 对文本进行正则分词（`\w+` 提取英文单词和中文字符）
2. 对每个 token 计算 MD5 哈希
3. 取哈希值模 embedding_dim，得到该 token 在向量中的位置
4. 在该位置累加 1.0（类似词袋模型）
5. 最后 L2 归一化，使向量长度为 1

**特点：**
- 确定性：相同文本始终产生相同向量
- 无需模型：不依赖 GPU 或外部服务
- 质量有限：哈希冲突会导致不同 token 映射到同一位置，但对于开发测试足够

### 3.4 分词器

```python
def tokenize(self, text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())
```

简单的正则分词，将文本转为小写后提取所有"单词字符"序列。对中文而言，每个汉字被视为一个 token。

### 3.5 批量嵌入

```python
def embed_many(self, texts: list[str]) -> list[list[float]]:
    return [self.embed_text(t) for t in texts]
```

当前为逐条嵌入。如果使用 Ollama Provider，Ollama 的 `/api/embed` 端点原生支持批量输入，性能更好。

---

## 4. BM25Service — 词法检索

**文件：** `app/services/bm25_service.py`

### 4.1 什么是 BM25

BM25（Best Matching 25）是信息检索领域最经典的排序函数之一，基于**词频-逆文档频率**（TF-IDF）改进而来。

### 4.2 算法公式

对于查询 Q 和文档 D，BM25 分数为：

```
score(Q, D) = Σ IDF(q) × (f(q,D) × (k1 + 1)) / (f(q,D) + k1 × (1 - b + b × |D|/avgdl))
```

其中：
- `f(q,D)` = 查询词 q 在文档 D 中的出现次数（词频）
- `|D|` = 文档 D 的长度（token 数）
- `avgdl` = 所有文档的平均长度
- `k1` = 词频饱和参数（默认 1.5）
- `b` = 文档长度归一化参数（默认 0.75）
- `IDF(q)` = 逆文档频率

### 4.3 实现详解

```python
class BM25Service:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75):
        self._k1 = k1
        self._b = b

    def score(self, query: str, chunks: list[Chunk], top_k: int) -> list[dict]:
```

**步骤分解：**

**第 1 步：分词**
```python
query_tokens = re.findall(r"\w+", query.lower())
```

**第 2 步：构建文档词频表**
```python
doc_tokens = [re.findall(r"\w+", c.content.lower()) for c in chunks]
doc_tf = [Counter(tokens) for tokens in doc_tokens]
```

**第 3 步：计算平均文档长度**
```python
doc_lengths = [len(t) for t in doc_tokens]
avgdl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1
```

**第 4 步：计算 IDF**
```python
N = len(chunks)  # 文档总数
for token in query_tokens:
    df = sum(1 for tf in doc_tf if token in tf)  # 包含该词的文档数
    idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
```

IDF 公式带有平滑项（+0.5），避免 df=0 或 df=N 时的极端值。

**第 5 步：计算 BM25 分数**
```python
for i, chunk in enumerate(chunks):
    score = 0.0
    for token in query_tokens:
        tf = doc_tf[i].get(token, 0)
        numerator = tf * (self._k1 + 1)
        denominator = tf + self._k1 * (1 - self._b + self._b * doc_lengths[i] / avgdl)
        score += idf[token] * numerator / denominator
```

**第 6 步：排序返回 top_k**

### 4.4 参数调优指南

| 参数 | 默认值 | 增大效果 | 减小效果 |
|------|--------|---------|---------|
| k1 | 1.5 | 词频的影响更大（偏向长文档） | 词频的影响减小（趋向 binary matching） |
| b | 0.75 | 文档长度的惩罚更强（偏向短文档） | 文档长度的影响减小（长短文档同等对待） |

当 k1=0 时，BM25 退化为 IDF 加权的 Boolean Matching。
当 b=0 时，完全忽略文档长度差异。

---

## 5. HybridSearchService — RRF 混合融合

**文件：** `app/services/hybrid_service.py`

### 5.1 什么是 RRF

RRF（Reciprocal Rank Fusion）是一种简单而有效的**排名融合算法**，用于将多个排序列表合并为一个综合排序。

### 5.2 算法公式

```
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

其中：
- `d` = 候选文档
- `rank_i(d)` = 文档 d 在第 i 个排序列表中的排名（从 1 开始）
- `k` = 常数（默认 60）

### 5.3 实现详解

```python
class HybridSearchService:
    def fuse(
        self,
        vector_hits: list[dict],
        lexical_hits: list[dict],
        top_k: int,
    ) -> list[dict]:
```

**步骤：**

```python
# 1. 构建 chunk_id → 综合分数 的映射
scores: dict[str, float] = {}
docs: dict[str, dict] = {}

# 2. 向量检索结果贡献 RRF 分数
for rank, hit in enumerate(vector_hits, start=1):
    cid = hit["chunk_id"]
    scores[cid] = scores.get(cid, 0) + 1.0 / (60 + rank)
    docs[cid] = hit

# 3. 词法检索结果贡献 RRF 分数
for rank, hit in enumerate(lexical_hits, start=1):
    cid = hit["chunk_id"]
    scores[cid] = scores.get(cid, 0) + 1.0 / (60 + rank)
    if cid not in docs:
        docs[cid] = hit

# 4. 按综合分数降序排序，取 top_k
ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
return [{"score": score, **docs[cid]} for cid, score in ranked]
```

### 5.4 为什么 k=60

k 值控制排名靠后的文档对最终分数的影响：

| k 值 | rank=1 的贡献 | rank=10 的贡献 | 特点 |
|------|-------------|---------------|------|
| 1 | 0.500 | 0.091 | 排名差异影响大 |
| 60 | 0.016 | 0.014 | 排名差异影响小 |
| 100 | 0.010 | 0.009 | 几乎不区分排名 |

k=60 是论文推荐值，在多数场景下表现良好。它使得排名前几的结果分数接近，减少单一检索器主导融合结果的风险。

### 5.5 RRF vs 加权平均

| 维度 | RRF | 加权平均 |
|------|-----|---------|
| 是否需要校准分数 | 不需要（只用排名） | 需要（两种分数量纲必须可比） |
| 超参数 | k（通常固定） | α 权重（需要调优） |
| 对异常分数的鲁棒性 | 高 | 低 |
| 实现复杂度 | 低 | 低 |

---

## 6. RerankService — 重排序

**文件：** `app/services/rerank_service.py`

### 6.1 职责

在初始检索结果基础上，通过更细粒度的匹配进一步优化排序。

### 6.2 当前实现：Token 重叠度重排序

```python
class RerankService:
    def rerank(self, query: str, hits: list[dict]) -> list[dict]:
        query_tokens = set(re.findall(r"\w+", query.lower()))

        for hit in hits:
            text_tokens = set(re.findall(r"\w+", hit.get("text", "").lower()))
            overlap = query_tokens & text_tokens  # 交集
            hit["score"] = hit.get("score", 0.0) + 0.05 * len(overlap)

        return sorted(hits, key=lambda x: x["score"], reverse=True)
```

**工作原理：**
1. 将查询和每个命中文本分别分词
2. 计算两者的 token 交集大小
3. 每个重叠 token 给分数加 0.05
4. 按新分数重新排序

**局限性：**
- 只做精确匹配，不考虑语义相似度
- 对于同义词（如 "大模型" 和 "LLM"）无效
- 生产环境应替换为 Cross-Encoder 模型（如 BGE-Reranker）

### 6.3 可选改进方向

```
当前: Token Overlap (简单、快速、无依赖)
  ↓
进阶: Cross-Encoder Reranker (准确但慢)
  例如: BAAI/bge-reranker-v2-m3
  方式: 将 (query, text) 对输入模型，输出相关性分数

  ↓
高级: LLM-as-a-Judge Reranker
  方式: 让 LLM 判断每个结果与查询的相关性
```

---

## 7. ChunkService — 文本提取与分块

**文件：** `app/services/chunk_service.py`

### 7.1 文本提取

```python
def extract_text(self, file_path: str) -> str:
```

| 文件类型 | 提取方式 |
|---------|---------|
| `.txt`, `.md`, `.py`, `.rs` | UTF-8 读取全文 |
| `.pdf` | 使用 PyPDF 的 `PdfReader` 逐页提取文本 |

### 7.2 滑动窗口分块算法

```python
def chunk_text(self, text: str, source: str) -> list[dict]:
```

**核心参数：**
- `CHUNK_SIZE` = 600（字符）：每个分块的目标大小
- `CHUNK_OVERLAP` = 100（字符）：相邻分块的重叠部分

**算法可视化：**

```
原始文本：[============================== ... ============================]
           |<--- 600 字符 --->|
                        |<- 100 ->|
                        |<--- 600 字符 --->|
                                     |<- 100 ->|
                                     |<--- 600 字符 --->|

分块结果：
Chunk 0:   [============]
Chunk 1:       [============]      ← 与 Chunk 0 重叠 100 字符
Chunk 2:           [============]  ← 与 Chunk 1 重叠 100 字符
```

**为什么需要重叠：**

不重叠的分块可能把一个完整的语句或概念切断在两个分块之间。重叠确保边界附近的内容在相邻分块中都出现，提高检索命中率。

**实现代码：**

```python
step = settings.chunk_size - settings.chunk_overlap  # 步长 = 600 - 100 = 500
chunks = []
for i in range(0, len(text), step):
    chunk_text = text[i : i + settings.chunk_size]
    if chunk_text.strip():  # 跳过空白
        chunks.append({
            "content": chunk_text,
            "chunk_index": len(chunks),
            "source": source,
            "token_count": len(chunk_text.split()),
            "char_count": len(chunk_text),
        })
```

### 7.3 分块存储

```python
def replace_document_chunks(self, db: Session, document_id: str, chunks: list[dict]) -> list[Chunk]:
```

这是一个**原子替换**操作：
1. 删除该文档的所有旧 Chunk
2. 创建新的 Chunk 记录
3. 在同一个事务中提交

这确保了重新处理文档时不会产生重复分块。

---

## 8. LLMService — 大模型调用

**文件：** `app/services/llm_service.py`

### 8.1 Prompt 构建

```python
def _build_messages(self, query: str, hits: list[dict]) -> list[dict[str, str]]:
```

构建标准的 chat messages 格式：

```python
[
    {
        "role": "system",
        "content": "你是一个面向知识库问答场景的中文 AI 助手。"
                   "请根据提供的检索上下文回答用户问题。"
                   "如果上下文中没有相关信息，请据实回答。"
    },
    {
        "role": "user",
        "content": f"问题：{query}\n\n检索上下文：\n{context}"
    }
]
```

**上下文构建：** 取检索结果的前 5 条，格式化为带编号和来源的文本：

```
[1] (来源: 深度学习入门.pdf) 注意力机制是深度学习中的一种重要技术...
[2] (来源: RAG笔记.md) RAG 通过检索增强生成来减少幻觉...
```

### 8.2 调用 LLM

```python
def answer(self, query: str, hits: list[dict]) -> str:
    messages = self._build_messages(query, hits)
    registry = ProviderRegistry.get_instance()
    llm = registry.get_llm()

    if llm is None:
        return "LLM provider not configured..."

    response = llm.chat_completion(messages)
    return response.content
```

### 8.3 带元数据的回答

```python
def answer_with_metadata(self, query: str, hits: list[dict]) -> dict:
    # ... 调用 LLM ...
    return {
        "answer": response.content,
        "model_version": response.metadata.get("ab_model", response.model),
    }
```

`model_version` 字段在 A/B 测试场景下特别有用——前端可以展示每个回答由哪个模型生成，便于用户比较。

---

## 9. CacheService — 缓存服务

**文件：** `app/services/cache_service.py`

### 9.1 缓存键设计

```python
def _key(self, namespace: str, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"rag-platform:{namespace}:{digest}"
```

**键格式：** `rag-platform:search:a1b2c3d4...`

**为什么用 SHA256：**
- 查询参数可能很长（query 文本），直接作为 Redis key 效率低
- `sort_keys=True` 确保参数顺序不影响 key（`{a:1, b:2}` 和 `{b:2, a:1}` 产生相同 key）
- 固定 64 字符长度，key 大小可控

### 9.2 读写操作

```python
def get_json(self, namespace: str, payload: dict) -> Any:
    client = get_redis_safe()
    if client is None:
        return None  # Redis 不可用时静默跳过
    key = self._key(namespace, payload)
    raw = client.get(key)
    if raw:
        CACHE_HITS.inc()
        return json.loads(raw)
    CACHE_MISSES.inc()
    return None

def set_json(self, namespace: str, payload: dict, value: Any, ttl: int = None):
    client = get_redis_safe()
    if client is None:
        return
    key = self._key(namespace, payload)
    ttl = ttl or settings.search_cache_ttl_seconds  # 默认 300 秒
    client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
```

### 9.3 命名空间失效

```python
def clear_namespace(self, namespace: str):
    client = get_redis_safe()
    if client is None:
        return
    pattern = f"rag-platform:{namespace}:*"
    keys = client.keys(pattern)
    if keys:
        client.delete(*keys)
```

**触发时机：**
- 文档入库完成后 → 清除 `"search"` 命名空间
- 向量索引完成后 → 清除 `"search"` 命名空间

### 9.4 优雅降级

`get_redis_safe()` 在连接失败时返回 `None`，所有缓存操作在 client 为 None 时静默跳过。这意味着 Redis 不可用时系统正常运行，只是失去缓存加速。

---

## 10. DocumentService & TaskService — 文档与任务管理

**文件：** `app/services/document_service.py`

### 10.1 DocumentService

| 方法 | 功能 |
|------|------|
| `create_document(db, ...)` | 创建文档记录（UUID, filename, hash, status="uploaded"） |
| `delete_document(db, document_id)` | 级联删除：PostgreSQL 记录 + LanceDB 向量 + 磁盘文件 + Redis 缓存 |
| `get_dashboard_stats(db)` | 聚合统计：文档数、分块数、任务数 |
| `find_duplicate(db, content_hash, kb)` | 基于 SHA256 哈希查找重复文档 |

### 10.2 TaskService

| 方法 | 功能 |
|------|------|
| `create_task(db, document_id, task_type)` | 创建任务记录（status="queued"） |
| `get_task(db, task_id)` | 查询任务状态 |
| `update_task(db, task_id, status, error)` | 更新任务状态（processing → completed/failed） |
| `increment_retry(db, task_id)` | 重试计数 +1，重置状态为 "queued" |

### 10.3 去重机制详解

```
上传文件 → 读取内容 → SHA256(content) → content_hash
  │
  ├── find_duplicate(content_hash, knowledge_base) → 找到匹配
  │     └── 返回已有 document_id, status="deduplicated"
  │
  └── 未找到匹配
        └── 正常创建文档 → 触发入库任务
```

去重范围是**同一 knowledge_base 内**。不同知识库可以有相同内容的文档。
