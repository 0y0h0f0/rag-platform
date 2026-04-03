# RAG Platform 测试指南

> 测试策略、运行方式、现有测试覆盖范围和编写规范。

---

## 目录

1. [测试总览](#1-测试总览)
2. [运行测试](#2-运行测试)
3. [现有测试详解](#3-现有测试详解)
4. [测试编写规范](#4-测试编写规范)
5. [Mocking 策略](#5-mocking-策略)
6. [评估与基准测试脚本](#6-评估与基准测试脚本)

---

## 1. 测试总览

### 1.1 测试层次

```
┌─────────────────────────────────────────┐
│           端到端测试 (E2E)                │  ← scripts/benchmark.py
│  测试完整 API 请求链路                    │     (需要服务运行)
├─────────────────────────────────────────┤
│           集成测试                        │  ← scripts/evaluate_retrieval.py
│  测试多个组件的协作                       │     (需要数据库和数据)
├─────────────────────────────────────────┤
│           单元测试                        │  ← tests/
│  测试单个 Service/函数的行为              │     (可独立运行)
└─────────────────────────────────────────┘
```

### 1.2 测试文件清单

| 文件 | 测试目标 | 类型 |
|------|---------|------|
| `tests/test_chunk_service.py` | 文本分块逻辑 | 单元测试 |
| `tests/test_cache_service.py` | 缓存键确定性 | 单元测试 |
| `tests/test_llm_service.py` | LLM 服务配置验证 | 单元测试 |
| `tests/test_bm25_service.py` | BM25 评分算法 | 单元测试 |
| `tests/test_hybrid_service.py` | RRF 融合算法 | 单元测试 |
| `tests/test_rerank_service.py` | 重排序逻辑 | 单元测试 |
| `scripts/evaluate_retrieval.py` | 检索质量评估 | 集成测试 |
| `scripts/benchmark.py` | API 延迟基准测试 | E2E |

---

## 2. 运行测试

### 2.1 运行所有单元测试

```bash
pytest tests/
```

### 2.2 运行指定测试文件

```bash
pytest tests/test_chunk_service.py
```

### 2.3 运行指定测试函数

```bash
pytest tests/test_chunk_service.py::test_chunk_text_splits_long_text
```

### 2.4 显示详细输出

```bash
pytest tests/ -v
```

### 2.5 显示打印输出（不捕获 stdout）

```bash
pytest tests/ -s
```

### 2.6 运行并生成覆盖率报告

```bash
pip install pytest-cov
pytest tests/ --cov=app --cov-report=term-missing
```

---

## 3. 现有测试详解

### 3.1 test_chunk_service.py — 文本分块

```python
def test_chunk_text_splits_long_text():
    """验证超过 chunk_size 的文本被正确分割成多个分块。"""
    service = ChunkService()
    text = "a " * 1000   # 2000 字符的文本
    chunks = service.chunk_text(text, source="test.txt")
    assert len(chunks) > 1                    # 应产生多个分块
    assert all(c["source"] == "test.txt" for c in chunks)  # 来源正确
```

**测试要点：**
- 验证长文本被分割
- 验证分块元数据正确

### 3.2 test_cache_service.py — 缓存键确定性

```python
def test_cache_key_is_deterministic():
    """验证相同的参数始终生成相同的缓存键。"""
    service = CacheService()
    key1 = service._key("search", {"query": "test", "top_k": 5})
    key2 = service._key("search", {"query": "test", "top_k": 5})
    assert key1 == key2   # 相同输入 → 相同键
```

**测试要点：**
- 缓存键的确定性是缓存正确工作的前提
- SHA256 哈希 + sort_keys 确保参数顺序不影响结果

### 3.3 test_llm_service.py — LLM 配置验证

```python
def test_llm_service_requires_api_key():
    """验证未配置 API Key 时，LLM 服务返回适当的错误消息。"""
    # 测试在 LLM_PROVIDER=deepseek 但未设置有效 API Key 时的行为
```

**测试要点：**
- 验证错误路径的用户友好性
- 确保未配置时不会崩溃

### 3.4 test_bm25_service.py — BM25 评分

```python
def test_bm25_scores_relevant_higher():
    """验证包含查询词的文档得分高于不包含的。"""
    service = BM25Service()
    # 构造测试数据...
    results = service.score("向量数据库", chunks, top_k=2)
    assert results[0]["score"] > results[1]["score"]
```

### 3.5 test_hybrid_service.py — RRF 融合

```python
def test_rrf_fusion_combines_results():
    """验证 RRF 正确合并两个排序列表。"""
    service = HybridSearchService()
    vector_hits = [{"chunk_id": "a", ...}, {"chunk_id": "b", ...}]
    lexical_hits = [{"chunk_id": "b", ...}, {"chunk_id": "c", ...}]
    fused = service.fuse(vector_hits, lexical_hits, top_k=3)
    # 'b' 同时出现在两个列表中，应排名靠前
    assert fused[0]["chunk_id"] == "b"
```

### 3.6 test_rerank_service.py — 重排序

```python
def test_rerank_boosts_overlap():
    """验证与查询有更多词重叠的结果排名更高。"""
    service = RerankService()
    hits = [
        {"chunk_id": "a", "text": "不相关的文本", "score": 0.5},
        {"chunk_id": "b", "text": "向量数据库是一种数据库", "score": 0.5},
    ]
    reranked = service.rerank("向量数据库", hits)
    assert reranked[0]["chunk_id"] == "b"  # 有更多重叠词
```

---

## 4. 测试编写规范

### 4.1 命名约定

```python
# 文件名: test_{module_name}.py
# 函数名: test_{what_is_being_tested}_{expected_behavior}

def test_chunk_text_splits_long_text():       # 好
def test_chunk_text_handles_empty_input():    # 好
def test_chunk():                             # 不好（太模糊）
```

### 4.2 测试结构 (AAA 模式)

```python
def test_bm25_scores_relevant_higher():
    # Arrange — 准备测试数据
    service = BM25Service()
    chunks = [create_test_chunk("向量数据库介绍"), create_test_chunk("天气预报")]

    # Act — 执行被测方法
    results = service.score("向量数据库", chunks, top_k=2)

    # Assert — 验证结果
    assert results[0]["score"] > results[1]["score"]
```

### 4.3 测试独立性

每个测试应该：
- 不依赖其他测试的执行顺序
- 不依赖外部服务（数据库、Redis、Ollama）
- 使用 mock 隔离外部依赖

### 4.4 创建测试辅助对象

```python
# 创建测试用 Chunk 对象
def create_test_chunk(content: str, chunk_index: int = 0) -> Chunk:
    chunk = Chunk()
    chunk.id = str(uuid.uuid4())
    chunk.document_id = "test-doc-id"
    chunk.content = content
    chunk.chunk_index = chunk_index
    chunk.source = "test.txt"
    chunk.status = "pending"
    return chunk
```

---

## 5. Mocking 策略

### 5.1 Mock Redis（缓存测试）

```python
from unittest.mock import patch, MagicMock

def test_cache_miss_returns_none():
    with patch("app.services.cache_service.get_redis_safe") as mock_redis:
        mock_client = MagicMock()
        mock_client.get.return_value = None
        mock_redis.return_value = mock_client

        service = CacheService()
        result = service.get_json("search", {"query": "test"})
        assert result is None
```

### 5.2 Mock LLM Provider

```python
from unittest.mock import patch, MagicMock
from app.infra.model_provider import LLMResponse

def test_llm_service_builds_correct_prompt():
    mock_provider = MagicMock()
    mock_provider.chat_completion.return_value = LLMResponse(
        content="测试回答",
        model="test-model",
    )

    with patch("app.infra.provider_registry.ProviderRegistry.get_instance") as mock_reg:
        mock_reg.return_value.get_llm.return_value = mock_provider

        service = LLMService()
        answer = service.answer("测试问题", [{"text": "上下文", "source": "test.txt"}])
        assert answer == "测试回答"
```

### 5.3 Mock 数据库 Session

```python
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

def test_document_service_create():
    db = MagicMock(spec=Session)
    service = DocumentService()
    service.create_document(db, filename="test.txt", ...)
    db.add.assert_called_once()
    db.commit.assert_called_once()
```

---

## 6. 评估与基准测试脚本

### 6.1 检索质量评估

**文件：** `scripts/evaluate_retrieval.py`

评估三种检索模式的质量：

```python
EVAL_CASES = [
    {"query": "什么是向量数据库", "expected_substring": "向量"},
    {"query": "分布式系统一致性", "expected_substring": "一致性"},
    # ...
]
```

**评估指标：**

| 指标 | 说明 |
|------|------|
| Hit@1 | 第 1 个结果是否包含期望内容 |
| Hit@3 | 前 3 个结果中是否有包含期望内容的 |

**运行方式：**

```bash
# 需要先加载演示数据
python scripts/load_demo_docs.py
python scripts/evaluate_retrieval.py
```

**输出示例：**

```
=== vector mode ===
Hit@1: 0.80  Hit@3: 1.00

=== lexical mode ===
Hit@1: 0.60  Hit@3: 0.80

=== hybrid mode ===
Hit@1: 0.80  Hit@3: 1.00
```

### 6.2 延迟基准测试

**文件：** `scripts/benchmark.py`

测量各检索模式的 API 响应延迟：

```bash
# 需要服务运行中
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
python scripts/benchmark.py
```

**输出示例：**

```
=== vector mode ===
  Avg latency: 45.2ms
  P95 latency: 78.1ms

=== lexical mode ===
  Avg latency: 32.1ms
  P95 latency: 55.3ms

=== hybrid mode ===
  Avg latency: 62.4ms
  P95 latency: 98.7ms
```

### 6.3 加载演示数据

**文件：** `scripts/load_demo_docs.py`

创建 3 个演示文档：
1. `distributed_systems.txt` — 分布式系统笔记
2. `rag_notes.txt` — RAG 技术笔记
3. `lancedb_notes.txt` — LanceDB 使用笔记

同步执行完整的入库流程（提取 → 分块 → 向量化 → 索引），无需 Celery Worker。
