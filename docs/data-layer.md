# RAG Platform 数据层技术文档

> 详细解析 `app/db/` 和 `app/models/` 中数据库设计、存储方案和数据访问模式。

---

## 目录

1. [数据层总览](#1-数据层总览)
2. [PostgreSQL — 关系型数据](#2-postgresql--关系型数据)
3. [LanceDB — 向量存储](#3-lancedb--向量存储)
4. [Redis — 缓存与消息队列](#4-redis--缓存与消息队列)
5. [ORM 模型详解](#5-orm-模型详解)
6. [数据库迁移 (Alembic)](#6-数据库迁移-alembic)
7. [双数据库设计决策](#7-双数据库设计决策)

---

## 1. 数据层总览

平台使用三个独立的数据存储组件，各司其职：

```
┌─────────────────────────────────────────────────────────────┐
│                       数据层架构                              │
│                                                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   PostgreSQL     │  │   LanceDB    │  │    Redis     │   │
│  │   (或 SQLite)    │  │              │  │              │   │
│  │                  │  │              │  │              │   │
│  │  结构化数据：      │  │  向量数据：   │  │  临时数据：   │   │
│  │  • 文档元数据     │  │  • 嵌入向量   │  │  • 搜索缓存  │   │
│  │  • 文本分块       │  │  • 文本副本   │  │  • 任务消息  │   │
│  │  • 任务状态       │  │  • 元数据索引 │  │              │   │
│  │                  │  │              │  │              │   │
│  │  文件：           │  │  文件：       │  │  进程：       │   │
│  │  postgres.py     │  │  lancedb_    │  │  redis_      │   │
│  │                  │  │  client.py   │  │  client.py   │   │
│  └─────────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. PostgreSQL — 关系型数据

**文件：** `app/db/postgres.py`

### 2.1 连接配置

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase):
    pass

# 自动检测数据库类型
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}  # SQLite 多线程安全

engine = create_engine(
    settings.database_url,
    future=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,      # 不自动刷新（手动控制 flush 时机）
    autocommit=False,     # 不自动提交（显式 commit）
    expire_on_commit=False,  # commit 后不过期对象（避免额外查询）
)
```

**关键参数解释：**

| 参数 | 值 | 说明 |
|------|----|------|
| `autoflush=False` | 禁止自动刷新 | 避免在查询前意外触发 SQL，提高可预测性 |
| `autocommit=False` | 禁止自动提交 | 所有写操作需要显式 `db.commit()`，确保事务边界清晰 |
| `expire_on_commit=False` | 提交后不过期 | 避免 commit 后访问对象属性时触发额外 SELECT |
| `check_same_thread=False` | 仅 SQLite | SQLite 默认不允许跨线程使用同一连接，此参数放宽限制 |

### 2.2 Session 管理

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

作为 FastAPI 依赖注入使用：

```python
@router.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    return db.query(Document).all()
```

**生命周期：** 每个 HTTP 请求创建一个 Session，请求结束时自动关闭。这是 "Session-per-Request" 模式。

### 2.3 数据库初始化

```python
def init_db() -> None:
    import app.models.document   # 确保模型被导入
    import app.models.chunk
    import app.models.task
    Base.metadata.create_all(bind=engine)
```

在 FastAPI startup 事件中调用，自动创建所有表（如果不存在）。

### 2.4 开发/生产切换

| 环境 | DATABASE_URL | 特点 |
|------|-------------|------|
| 开发 | `sqlite:///./data/app.db` | 零依赖，单文件数据库 |
| 生产 | `postgresql+psycopg://user:pass@host:5432/db` | ACID 事务，高并发 |

切换只需修改 `.env` 中的 `DATABASE_URL`，代码零改动。

---

## 3. LanceDB — 向量存储

**文件：** `app/db/lancedb_client.py`

### 3.1 什么是 LanceDB

LanceDB 是一个**嵌入式向量数据库**，基于 Lance 列存格式。与 Pinecone、Weaviate 等托管服务不同，LanceDB 以库的形式运行在应用进程内，数据存储为本地文件。

**特点：**
- 零网络开销（与 PostgreSQL + pgvector 相比）
- 支持 ANN 搜索（近似最近邻）
- 基于 PyArrow，与 pandas/numpy 无缝集成
- 数据文件存储在 `./data/lancedb/`

### 3.2 表结构 (Schema)

```python
def ensure_table(self):
    schema = pa.schema([
        pa.field("chunk_id", pa.string()),                          # 关联 PG chunks.id
        pa.field("document_id", pa.string()),                      # 关联 PG documents.id
        pa.field("knowledge_base", pa.string()),                   # 知识库隔离
        pa.field("text", pa.string()),                             # 原文（检索后直接返回）
        pa.field("vector", pa.list_(pa.float32(), self._dim)),     # 向量
        pa.field("source", pa.string()),                           # 来源文件名
        pa.field("chunk_index", pa.int32()),                       # 块序号
    ])
    self.db.create_table(self.table_name, schema=schema)
```

**为什么在 LanceDB 中冗余存储 text：**
- 避免检索后再查 PostgreSQL 获取文本（减少一次数据库往返）
- LanceDB 的列存格式在不查询 text 列时不会加载该列数据

### 3.3 写入操作

```python
def add_chunks(self, rows: list[dict]):
    table = self.table()
    table.add(rows)
```

`rows` 是字典列表，每个字典包含 schema 中定义的所有字段。批量写入，性能优于逐条插入。

### 3.4 向量搜索

```python
def search(
    self,
    query_vector: list[float],
    top_k: int = 5,
    document_id: str | None = None,
    knowledge_base: str | None = None,
) -> list[dict]:
    table = self.table()
    query = table.search(query_vector).limit(top_k)

    # 条件过滤
    if document_id:
        query = query.where(f"document_id = '{document_id}'")
    if knowledge_base:
        query = query.where(f"knowledge_base = '{knowledge_base}'")

    results = query.to_list()
    return results
```

**搜索流程：**
1. 传入查询向量
2. LanceDB 计算与所有存储向量的余弦距离
3. 返回距离最近的 top_k 条结果
4. 可选地按 `document_id` 或 `knowledge_base` 过滤

**返回格式：** 每条结果包含所有 schema 字段 + `_distance` 字段（余弦距离）。

### 3.5 删除操作

```python
def delete_document(self, document_id: str):
    table = self.table()
    table.delete(f"document_id = '{document_id}'")
```

按 `document_id` 批量删除，用于文档删除时清理向量数据。

### 3.6 维度自适应

当使用 Ollama Embedding Provider 时，ProviderRegistry 会自动检测实际的向量维度：

```python
# provider_registry.py 中
def _auto_detect_embedding_dim(self):
    actual_dim = self._embedding_provider.probe_dimension()  # 发送测试请求
    if actual_dim != settings.embedding_dim:
        # 维度不匹配 → 删除旧表，以新维度重建
        lancedb_client.drop_table()
        settings.embedding_dim = actual_dim
        lancedb_client.ensure_table()
```

这确保了切换 Embedding 模型（如从 64 维的 local hash 切换到 768 维的 nomic-embed-text）时表结构自动适配。

---

## 4. Redis — 缓存与消息队列

**文件：** `app/db/redis_client.py`

### 4.1 连接方式

```python
def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)

def get_redis_safe() -> Redis | None:
    try:
        client = get_redis()
        client.ping()
        return client
    except Exception:
        return None
```

**两种接口的区别：**

| 接口 | 行为 | 使用场景 |
|------|------|---------|
| `get_redis()` | 连接失败抛异常 | Celery Broker（任务队列必须可用） |
| `get_redis_safe()` | 连接失败返回 None | 缓存层（Redis 不可用时降级为无缓存） |

### 4.2 Redis 在系统中的角色

| 角色 | Redis DB | 用途 |
|------|----------|------|
| 搜索缓存 | DB 0 | 缓存检索结果（`CacheService`） |
| Celery Broker | DB 0/1 | 任务消息队列 |
| Celery Backend | DB 1/2 | 任务结果存储 |

### 4.3 `decode_responses=True`

这个参数让 Redis 客户端自动将返回的 bytes 解码为 str，避免在代码中频繁 `.decode("utf-8")`。

---

## 5. ORM 模型详解

**文件：** `app/models/`

### 5.1 数据库 ER 图

```
┌──────────────────────────────┐
│          documents           │
├──────────────────────────────┤
│ id          VARCHAR(36) [PK] │
│ filename    VARCHAR(255)     │
│ content_type VARCHAR(128)    │
│ storage_path TEXT             │
│ file_size   INTEGER          │
│ content_hash VARCHAR(64)     │ ← SHA256，用于去重 (INDEX)
│ knowledge_base VARCHAR(128)  │ ← 知识库隔离 (INDEX)
│ status      VARCHAR(32)      │ ← uploaded→processing→indexed|failed
│ created_at  DATETIME         │
│ updated_at  DATETIME         │
└──────────┬───────────────────┘
           │ 1:N (CASCADE DELETE)
           │
┌──────────▼───────────────────┐
│          chunks              │
├──────────────────────────────┤
│ id          VARCHAR(36) [PK] │
│ document_id VARCHAR(36) [FK] │ ← INDEX
│ chunk_index INTEGER          │
│ content     TEXT              │ ← 分块文本
│ token_count INTEGER          │
│ char_count  INTEGER          │
│ source      VARCHAR(255)     │
│ status      VARCHAR(32)      │ ← pending→indexed
│ created_at  DATETIME         │
└──────────────────────────────┘

┌──────────────────────────────┐
│          tasks               │
├──────────────────────────────┤
│ id          VARCHAR(36) [PK] │
│ document_id VARCHAR(36) [FK] │ ← SET NULL on delete
│ task_type   VARCHAR(64)      │ ← "ingest_and_index"
│ status      VARCHAR(32)      │ ← queued→processing→completed|failed
│ celery_task_id VARCHAR(64)   │
│ error_message TEXT           │
│ retry_count INTEGER          │
│ created_at  DATETIME         │
│ finished_at DATETIME         │
└──────────────────────────────┘
```

### 5.2 Document 模型

```python
class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=True)
    storage_path = Column(Text, nullable=True)
    file_size = Column(Integer, default=0)
    content_hash = Column(String(64), nullable=True, index=True)   # 去重索引
    knowledge_base = Column(String(128), default="default", index=True)
    status = Column(String(32), default="uploaded")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chunks = relationship("Chunk", back_populates="document",
                          cascade="all, delete-orphan")  # 级联删除
    tasks = relationship("TaskRecord", back_populates="document")
```

**状态流转：**
```
uploaded → processing → indexed (成功)
                      → failed  (失败)
```

### 5.3 Chunk 模型

```python
class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id"), index=True)
    chunk_index = Column(Integer, nullable=False)  # 在文档中的位置
    content = Column(Text, nullable=False)          # 分块文本
    token_count = Column(Integer, default=0)
    char_count = Column(Integer, default=0)
    source = Column(String(255), nullable=True)     # 来源文件名
    status = Column(String(32), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")
```

**状态流转：**
```
pending → indexed (向量化并写入 LanceDB 后)
```

### 5.4 TaskRecord 模型

```python
class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"),
                         nullable=True)
    task_type = Column(String(64), nullable=False)
    status = Column(String(32), default="pending")
    celery_task_id = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    document = relationship("Document", back_populates="tasks")
```

**为什么 document_id 用 SET NULL 而非 CASCADE：**
删除文档后，任务记录应保留用于审计和排查（可以看到哪些任务失败过，何时完成的等）。

### 5.5 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 主键 | UUID v4 | 分布式环境下无冲突，不泄露记录数量 |
| 时间戳 | `datetime.utcnow` | 统一使用 UTC，避免时区混乱 |
| 级联策略 | Document→Chunk: CASCADE | 删除文档时自动清理分块 |
| 级联策略 | Document→Task: SET NULL | 保留任务记录用于审计 |
| 索引 | content_hash, knowledge_base | 加速去重查询和知识库过滤 |

---

## 6. 数据库迁移 (Alembic)

### 6.1 配置

```ini
# alembic.ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite:///./data/app.db  # 被 env.py 中的 settings 覆盖
```

### 6.2 迁移历史

| 版本 | 文件 | 内容 |
|------|------|------|
| 0001 | `20260401_0001_initial.py` | 创建 documents, chunks, tasks 三张表 |
| 0002 | `20260401_0002_version5_reliability.py` | 添加 content_hash（去重）和 retry_count（任务重试） |

### 6.3 常用命令

```bash
# 查看当前迁移版本
alembic current

# 应用所有迁移
alembic upgrade head

# 回退一步
alembic downgrade -1

# 创建新迁移（自动检测模型变更）
alembic revision --autogenerate -m "add new column"
```

### 6.4 env.py 配置

`alembic/env.py` 从 `app.core.config` 读取实际的 `DATABASE_URL`，而非使用 `alembic.ini` 中的硬编码值。这确保迁移总是针对当前配置的数据库执行。

---

## 7. 双数据库设计决策

### 7.1 为什么不只用 PostgreSQL + pgvector

| 维度 | PostgreSQL + pgvector | PostgreSQL + LanceDB |
|------|----------------------|---------------------|
| 向量搜索性能 | 依赖 HNSW/IVFFlat 索引，内存开销大 | LanceDB 使用 Lance 列存优化，I/O 更高效 |
| 索引竞争 | 向量索引和 B-Tree 索引竞争内存 | 各自独立，互不影响 |
| 运维复杂度 | 需要调优 pgvector 参数 | LanceDB 零运维（嵌入式） |
| 独立扩展 | 无法单独扩展向量搜索 | 可以独立替换向量存储 |
| 开发体验 | 需要安装 pgvector 扩展 | pip install lancedb 即可 |

### 7.2 为什么不只用 LanceDB

LanceDB 不支持：
- ACID 事务（文档状态更新需要事务保证）
- 复杂查询（JOIN、聚合、子查询）
- 外键约束（数据完整性）

### 7.3 数据一致性

双数据库意味着同一个 Chunk 的数据分布在两处：
- PostgreSQL 存储元数据（id, document_id, status, content）
- LanceDB 存储向量和文本副本

**保持一致的策略：**
1. **写入顺序**：先写 PostgreSQL（分块），再写 LanceDB（向量化+索引）
2. **删除顺序**：先删 LanceDB，再删 PostgreSQL（确保不会出现有向量但无元数据的情况）
3. **失败处理**：如果向量化失败，文档状态设为 `"failed"`，PostgreSQL 中的 Chunk 保留，可以重试

**潜在改进：** 引入 Outbox Pattern 或 Change Data Capture (CDC) 确保最终一致性。
