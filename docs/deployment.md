# RAG Platform 部署指南

本文档详细介绍 RAG Platform 的各种部署方式，从本地开发到 Kubernetes 生产环境。

---

## 目录

1. [环境要求](#1-环境要求)
2. [本地开发模式 (PostgreSQL)](#2-本地开发模式-postgresql)
3. [Ollama 本地 GPU 模式](#3-ollama-本地-gpu-模式)
4. [PostgreSQL 工程验证模式](#4-postgresql-工程验证模式)
5. [Docker Compose 完整部署](#5-docker-compose-完整部署)
6. [Kubernetes 生产部署](#6-kubernetes-生产部署)
7. [可观测性部署](#7-可观测性部署)
8. [配置参考表](#8-配置参考表)
9. [故障排查](#9-故障排查)

---

## 1. 环境要求

### 基础环境

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.11+ | 推荐 3.11.x |
| pip | 最新版 | 或使用 conda 管理 |
| Git | 2.x+ | 代码版本管理 |

### 容器化部署

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Docker | 24.0+ | 容器运行时 |
| Docker Compose | v2.20+ | 多容器编排 |
| NVIDIA Container Toolkit | 最新版 | Ollama GPU 模式必需 |

### Kubernetes 生产部署

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Kubernetes | 1.28+ | 集群版本 |
| kubectl | 与集群版本匹配 | 集群管理工具 |
| nvidia-device-plugin | 最新版 | GPU 节点必需 |

### GPU 支持（Ollama GPU 模式）

| 组件 | 要求 |
|------|------|
| GPU | NVIDIA RTX 4060 (8GB) 或更高 |
| 驱动 | NVIDIA Driver 535+ |
| CUDA | 12.x（由 Ollama 自动管理） |
| Ollama | 最新版 |

---

## 2. 本地开发模式 (PostgreSQL)

本地开发默认使用 PostgreSQL 作为业务数据库，本地哈希作为嵌入后端，和容器部署保持一致。

### 2.1 克隆项目

```bash
git clone https://github.com/0y0h0f0/rag-platform.git
cd rag-platform
```

### 2.2 安装依赖

使用 pip：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

或使用 conda：

```bash
conda create -n rag python=3.11 -y
conda activate rag
pip install -r requirements.txt
```

### 2.3 配置环境变量

```bash
cp .env.example .env
```

默认 `.env` 配置即可用于本地开发，核心默认值：

```ini
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/rag_platform
REDIS_URL=redis://localhost:6379/0
CELERY_TASK_ALWAYS_EAGER=true
EMBEDDING_BACKEND=local
EMBEDDING_PROVIDER=legacy
LLM_PROVIDER=deepseek
LLM_API_KEY=your-api-key-here   # 替换为你的 DeepSeek API Key
```

> **说明**：`CELERY_TASK_ALWAYS_EAGER=true` 表示 Celery 任务同步执行，无需启动 Redis 和 Worker 进程，但本地仍需先启动 PostgreSQL。

### 2.4 初始化数据库

```bash
# 启动 PostgreSQL
docker run -d \
  --name rag-postgres \
  -e POSTGRES_DB=rag_platform \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:16

# 创建数据目录
mkdir -p data/uploads

# 运行数据库迁移
alembic upgrade head
```

### 2.5 加载演示数据（可选）

```bash
python scripts/load_demo_docs.py
```

### 2.6 启动服务

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2.7 验证

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# API 文档
# 浏览器访问 http://127.0.0.1:8000/docs
```

---

## 3. Ollama 本地 GPU 模式

使用 Ollama 在本地 GPU 上运行 LLM 和 Embedding 模型，无需外部 API 调用。

### 3.1 安装 Ollama

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# 或从 https://ollama.com/download 下载安装包
```

### 3.2 启动 Ollama 服务

```bash
ollama serve
```

> Ollama 默认监听 `http://localhost:11434`。

### 3.3 拉取模型

```bash
# LLM 模型 - Qwen2.5 7B 4bit 量化版（约 4.7GB）
ollama pull qwen2.5:7b-instruct-q4_K_M

# Embedding 模型（约 274MB）
ollama pull nomic-embed-text
```

#### RTX 4060 (8GB) 推荐模型与量化选择

| 模型 | 量化 | 显存占用 | 推荐场景 |
|------|------|----------|----------|
| qwen2.5:7b-instruct-q4_K_M | Q4_K_M | ~5.2GB | 日常使用，性能与质量平衡 |
| qwen2.5:7b-instruct-q4_K_S | Q4_K_S | ~4.8GB | 显存紧张时使用 |
| qwen2.5:3b-instruct | FP16 | ~6GB | 小模型全精度 |
| nomic-embed-text | FP16 | ~0.3GB | Embedding，始终推荐 |

> **注意**：RTX 4060 8GB 显存运行 7B Q4 量化模型后，剩余显存约 2-3GB，足够同时运行 Embedding 模型。

### 3.4 配置 .env

```ini
# LLM 切换到 Ollama
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M

# Embedding 切换到 Ollama
EMBEDDING_PROVIDER=ollama
OLLAMA_EMBED_MODEL=nomic-embed-text
```

### 3.5 验证 Ollama

```bash
# 查看已下载模型
curl http://localhost:11434/api/tags

# 测试 LLM 推理
curl http://localhost:11434/api/generate -d '{
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "prompt": "你好",
  "stream": false
}'

# 测试 Embedding
curl http://localhost:11434/api/embeddings -d '{
  "model": "nomic-embed-text",
  "prompt": "测试文本"
}'
```

### 3.6 启动 RAG 服务

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 4. PostgreSQL 工程验证模式

如果你想把本地 PostgreSQL 切换成独立的验证实例或压测环境，可以按下面的方式单独启动。

### 4.1 启动 PostgreSQL

使用 Docker 快速启动：

```bash
docker run -d \
  --name rag-postgres \
  -e POSTGRES_DB=rag_platform \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:16
```

### 4.2 配置 .env

```ini
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/rag_platform
```

### 4.3 运行数据库迁移

```bash
alembic upgrade head
```

### 4.4 加载数据并验证

```bash
# 加载演示数据
python scripts/load_demo_docs.py

# 运行检索评估
python scripts/evaluate_retrieval.py

# 运行基准测试
python scripts/benchmark.py
```

---

## 5. Docker Compose 完整部署

一键启动完整的生产级环境，包含所有组件。

### 5.1 服务架构

`docker-compose.yml` 包含以下服务：

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| api | rag-platform (自构建) | 8000 | FastAPI 应用 |
| worker | rag-platform (自构建) | - | Celery Worker |
| postgres | postgres:16 | 5432 | 关系数据库 |
| redis | redis:7 | 6379 | 缓存 + 消息队列 |
| ollama | ollama/ollama:latest | 11434 | LLM + Embedding |
| jaeger | jaegertracing/all-in-one:latest | 16686, 4317 | 分布式追踪 |

### 5.2 启动服务

```bash
# 构建并启动所有服务
docker-compose up -d --build

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f api
```

### 5.3 首次模型拉取

Ollama 容器启动后需要手动拉取模型：

```bash
# 拉取 LLM 模型
docker exec -it rag-platform-ollama ollama pull qwen2.5:7b-instruct-q4_K_M

# 拉取 Embedding 模型
docker exec -it rag-platform-ollama ollama pull nomic-embed-text

# 验证模型列表
docker exec -it rag-platform-ollama ollama list
```

> **注意**：模型拉取需要时间，7B 模型约 4.7GB。模型数据存储在 `ollama_data` 卷中，重启不会丢失。

### 5.4 GPU 透传

`docker-compose.yml` 中 Ollama 服务已配置 NVIDIA GPU 透传：

```yaml
ollama:
  image: ollama/ollama:latest
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

确保宿主机已安装 NVIDIA Container Toolkit：

```bash
# 安装 NVIDIA Container Toolkit (Ubuntu)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

如果没有 GPU，可以在 `docker-compose.yml` 中删除 `deploy.resources` 段，Ollama 将使用 CPU 模式运行（速度较慢）。

### 5.5 数据库迁移

```bash
# 进入 api 容器执行迁移
docker exec -it rag-platform-api alembic upgrade head
```

### 5.6 数据持久化

| 卷名 | 挂载路径 | 说明 |
|------|----------|------|
| postgres_data | /var/lib/postgresql/data | PostgreSQL 数据 |
| ollama_data | /root/.ollama | Ollama 模型文件 |
| ./data | /app/data | LanceDB 向量数据 + 上传文件 |

### 5.7 端口映射总览

| 端口 | 服务 | 用途 |
|------|------|------|
| 8000 | API | FastAPI 应用入口 |
| 5432 | PostgreSQL | 数据库连接 |
| 6379 | Redis | 缓存/消息队列 |
| 11434 | Ollama | LLM/Embedding API |
| 16686 | Jaeger | 追踪 UI |
| 4317 | Jaeger | OTLP gRPC 接收端 |

### 5.8 验证部署

```bash
# API 健康检查
curl http://localhost:8000/health

# Ollama 状态
curl http://localhost:11434/api/tags

# Jaeger UI
# 浏览器访问 http://localhost:16686

# PostgreSQL 连接测试
docker exec -it rag-platform-postgres psql -U postgres -d rag_platform -c "SELECT 1;"
```

### 5.9 常见问题

**Ollama 模型拉取失败**：检查网络连接，可在宿主机先拉取后复制到容器卷中。

**API 启动报错连接 PostgreSQL 失败**：确保 PostgreSQL 容器完全启动后再启动 API。可以重启 API 容器：

```bash
docker-compose restart api worker
```

**GPU 不可用**：确认 `nvidia-smi` 在宿主机正常运行，并已安装 NVIDIA Container Toolkit。

---

## 6. Kubernetes 生产部署

### 6.1 前置条件

- Kubernetes 集群 1.28+
- 至少一个 GPU 节点，已安装 `nvidia-device-plugin`
- `kubectl` 已配置集群访问
- 容器镜像已推送到可访问的 Registry

```bash
# 验证集群状态
kubectl cluster-info

# 验证 GPU 节点
kubectl get nodes -l gpu=true

# 验证 nvidia-device-plugin
kubectl get pods -n kube-system | grep nvidia
```

### 6.2 构建并推送镜像

```bash
# 构建镜像
docker build -t your-registry.com/rag-platform:latest .

# 推送镜像
docker push your-registry.com/rag-platform:latest
```

> **注意**：部署前需将 `k8s/api-deployment.yaml` 和 `k8s/worker-deployment.yaml` 中的 `image: rag-platform:latest` 替换为实际的 Registry 地址。

### 6.3 部署步骤

按顺序执行以下命令：

```bash
# 1. 创建命名空间
kubectl apply -f k8s/namespace.yaml

# 2. 创建配置和密钥
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml

# 3. 创建持久化存储
kubectl apply -f k8s/postgres-pvc.yaml
kubectl apply -f k8s/lancedb-pvc.yaml

# 4. 部署基础设施服务
kubectl apply -f k8s/postgres-deployment.yaml
kubectl apply -f k8s/postgres-service.yaml
kubectl apply -f k8s/redis-deployment.yaml
kubectl apply -f k8s/redis-service.yaml

# 5. 部署 Ollama（需要 GPU 节点）
kubectl apply -f k8s/ollama-deployment.yaml
kubectl apply -f k8s/ollama-service.yaml

# 6. 部署 Jaeger
kubectl apply -f k8s/jaeger-deployment.yaml
kubectl apply -f k8s/jaeger-service.yaml

# 7. 等待基础设施就绪
kubectl -n rag-platform wait --for=condition=ready pod -l app=postgres --timeout=120s
kubectl -n rag-platform wait --for=condition=ready pod -l app=redis --timeout=60s
kubectl -n rag-platform wait --for=condition=ready pod -l app=ollama --timeout=300s

# 8. 部署应用服务
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/worker-deployment.yaml

# 9. 配置自动扩缩
kubectl apply -f k8s/api-hpa.yaml
kubectl apply -f k8s/worker-hpa.yaml
```

或一次性应用整个目录：

```bash
kubectl apply -f k8s/
```

### 6.4 ConfigMap 配置说明

`k8s/configmap.yaml` 中的关键配置：

```yaml
data:
  DATABASE_URL: "postgresql://postgres:postgres@postgres:5432/rag_platform"
  REDIS_URL: "redis://redis:6379/0"
  CELERY_BROKER_URL: "redis://redis:6379/1"
  CELERY_RESULT_BACKEND: "redis://redis:6379/2"
  CELERY_TASK_ALWAYS_EAGER: "false"        # 生产环境必须为 false
  LLM_PROVIDER: "ollama"                    # 使用 Ollama 作为 LLM
  EMBEDDING_PROVIDER: "ollama"              # 使用 Ollama 作为 Embedding
  OLLAMA_BASE_URL: "http://ollama:11434"    # K8s Service 名称
  OLLAMA_LLM_MODEL: "qwen2.5:7b-instruct-q4_K_M"
  OLLAMA_EMBED_MODEL: "nomic-embed-text"
  OTEL_ENABLED: "true"                      # 开启链路追踪
  OTEL_EXPORTER_ENDPOINT: "http://jaeger:4317"
  RATE_LIMIT_ENABLED: "true"
  RATE_LIMIT_REQUESTS_PER_MINUTE: "30"
```

### 6.5 Secret 管理

密钥通过 Kubernetes Secret 管理：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-platform-secret
  namespace: rag-platform
type: Opaque
data:
  LLM_API_KEY: Y2hhbmdlbWU=   # base64 编码的 API Key
```

修改 Secret：

```bash
# 生成 base64 编码
echo -n "your-actual-api-key" | base64

# 更新 Secret（修改 k8s/secret.yaml 中的值后）
kubectl apply -f k8s/secret.yaml

# 或直接命令行创建
kubectl -n rag-platform create secret generic rag-platform-secret \
  --from-literal=LLM_API_KEY=your-actual-api-key \
  --dry-run=client -o yaml | kubectl apply -f -
```

> **生产建议**：使用 External Secrets Operator 或 HashiCorp Vault 管理敏感信息，避免明文存储在 YAML 文件中。

### 6.6 Ollama StatefulSet（GPU 调度）

Ollama 使用 StatefulSet 部署，确保模型数据持久化：

```yaml
spec:
  nodeSelector:
    gpu: "true"              # 调度到带 GPU 标签的节点
  containers:
    - name: ollama
      image: ollama/ollama:latest
      resources:
        limits:
          nvidia.com/gpu: 1  # 请求 1 块 GPU
      volumeMounts:
        - name: ollama-models
          mountPath: /root/.ollama
  volumeClaimTemplates:
    - metadata:
        name: ollama-models
      spec:
        storage: 20Gi        # 模型存储空间
```

确保 GPU 节点已打标签：

```bash
kubectl label nodes <gpu-node-name> gpu=true
```

部署后拉取模型：

```bash
# 获取 Ollama Pod 名称
OLLAMA_POD=$(kubectl -n rag-platform get pod -l app=ollama -o jsonpath='{.items[0].metadata.name}')

# 拉取模型
kubectl -n rag-platform exec -it $OLLAMA_POD -- ollama pull qwen2.5:7b-instruct-q4_K_M
kubectl -n rag-platform exec -it $OLLAMA_POD -- ollama pull nomic-embed-text
```

### 6.7 API Deployment（健康探针）

API 服务配置了就绪探针和存活探针：

```yaml
readinessProbe:
  httpGet:
    path: /health/ready    # 就绪检查（依赖服务是否可用）
    port: 8000
  periodSeconds: 10
livenessProbe:
  httpGet:
    path: /health          # 存活检查
    port: 8000
  periodSeconds: 15
```

资源限制：

```yaml
resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
```

### 6.8 HPA 自动扩缩

API 和 Worker 均配置了 HPA：

```yaml
spec:
  scaleTargetRef:
    kind: Deployment
    name: api             # 或 worker
  minReplicas: 2          # 最小副本数
  maxReplicas: 5          # 最大副本数
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70   # CPU 使用率超过 70% 触发扩容
```

查看 HPA 状态：

```bash
kubectl -n rag-platform get hpa
```

### 6.9 持久化存储

| PVC 名称 | 容量 | 用途 |
|-----------|------|------|
| postgres-pvc | 10Gi | PostgreSQL 数据 |
| lancedb-pvc | 20Gi | LanceDB 向量数据 + 上传文件 |
| ollama-models (StatefulSet) | 20Gi | Ollama 模型文件 |

### 6.10 验证部署

```bash
# 查看所有 Pod 状态
kubectl -n rag-platform get pods

# 期望输出：
# NAME                        READY   STATUS    RESTARTS   AGE
# api-xxx-xxx                 1/1     Running   0          2m
# api-xxx-yyy                 1/1     Running   0          2m
# worker-xxx-xxx              1/1     Running   0          2m
# worker-xxx-yyy              1/1     Running   0          2m
# ollama-0                    1/1     Running   0          3m
# postgres-xxx-xxx            1/1     Running   0          3m
# redis-xxx-xxx               1/1     Running   0          3m
# jaeger-xxx-xxx              1/1     Running   0          3m

# 查看服务
kubectl -n rag-platform get svc

# 查看日志
kubectl -n rag-platform logs -f deployment/api
kubectl -n rag-platform logs -f deployment/worker

# 端口转发测试
kubectl -n rag-platform port-forward svc/api 8000:8000 &
curl http://localhost:8000/health

# Jaeger UI 端口转发
kubectl -n rag-platform port-forward svc/jaeger 16686:16686 &
# 浏览器访问 http://localhost:16686
```

### 6.11 数据库迁移（K8s 环境）

```bash
# 在 API Pod 中执行迁移
API_POD=$(kubectl -n rag-platform get pod -l app=api -o jsonpath='{.items[0].metadata.name}')
kubectl -n rag-platform exec -it $API_POD -- alembic upgrade head
```

---

## 7. 可观测性部署

### 7.1 OpenTelemetry 链路追踪

项目内置 OpenTelemetry 支持，配置以下环境变量启用：

```ini
OTEL_ENABLED=true
OTEL_EXPORTER_ENDPOINT=http://jaeger:4317   # Jaeger OTLP gRPC 端点
OTEL_SERVICE_NAME=rag-platform
```

启用后，以下操作将自动生成追踪 Span：
- HTTP 请求（FastAPI 自动注入）
- 数据库查询
- Celery 任务执行
- LLM / Embedding 调用

### 7.2 Jaeger UI

- **Docker Compose**：浏览器访问 `http://localhost:16686`
- **Kubernetes**：通过端口转发访问

```bash
kubectl -n rag-platform port-forward svc/jaeger 16686:16686
# 浏览器访问 http://localhost:16686
```

在 Jaeger UI 中：
1. 在 "Service" 下拉菜单中选择 `rag-platform`
2. 点击 "Find Traces" 查看请求链路
3. 点击具体 Trace 查看各环节耗时

### 7.3 Prometheus 指标

应用通过 `/metrics` 端点暴露 Prometheus 格式的指标：

```bash
curl http://localhost:8000/metrics
```

Kubernetes 环境中，配置 Prometheus 自动发现：

```yaml
# 在 API Deployment 的 Pod template 中添加注解
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8000"
    prometheus.io/path: "/metrics"
```

### 7.4 Grafana 集成

1. 添加 Prometheus 作为数据源
2. 添加 Jaeger 作为数据源（URL: `http://jaeger:16686`）
3. 创建 Dashboard 监控以下指标：
   - 请求延迟（P50/P95/P99）
   - 请求吞吐量（QPS）
   - 错误率
   - Celery 任务队列深度
   - LLM 调用延迟

推荐导入社区 Dashboard：
- FastAPI Dashboard ID: `16110`
- Redis Dashboard ID: `11835`
- PostgreSQL Dashboard ID: `9628`

---

## 8. 配置参考表

### 应用基础配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `APP_NAME` | `Distributed RAG Retrieval Platform` | 应用名称 |
| `API_PREFIX` | `/api/v1` | API 路由前缀 |
| `DATA_DIR` | `./data` | 数据文件根目录 |
| `UPLOAD_DIR` | `./data/uploads` | 文件上传目录 |

### 数据库配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/rag_platform` | 数据库连接串，默认使用本地 PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接地址 |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery 消息队列 Broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery 结果存储后端 |
| `CELERY_TASK_ALWAYS_EAGER` | `true` | 同步执行 Celery 任务（开发模式） |

### 向量数据库配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `LANCEDB_URI` | `./data/lancedb` | LanceDB 存储路径 |
| `LANCEDB_TABLE` | `chunks` | LanceDB 表名 |

### 文本分块配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `CHUNK_SIZE` | `600` | 文本分块大小（字符数） |
| `CHUNK_OVERLAP` | `100` | 分块重叠字符数 |

### Embedding 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `EMBEDDING_BACKEND` | `local` | 嵌入后端：`local`（哈希）/ `sentence-transformers` |
| `EMBEDDING_PROVIDER` | `legacy` | 嵌入提供者：`legacy` / `ollama` |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-zh-v1.5` | sentence-transformers 模型名 |
| `EMBEDDING_DIM` | `64` | 嵌入向量维度 |

### 检索配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TOP_K_DEFAULT` | `5` | 默认返回结果数 |
| `SEARCH_MODE_DEFAULT` | `vector` | 检索模式：`vector` / `lexical` / `hybrid` |
| `SEARCH_CACHE_TTL_SECONDS` | `300` | 搜索结果缓存 TTL（秒） |

### LLM 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `LLM_PROVIDER` | `deepseek` | LLM 提供者：`deepseek` / `ollama` / `api` / `ab_test` |
| `LLM_API_KEY` | `your-api-key-here` | API Key（DeepSeek 等外部 API） |
| `LLM_BASE_URL` | `https://api.deepseek.com` | LLM API 地址 |
| `LLM_MODEL` | `deepseek-chat` | LLM 模型名 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_MAX_TOKENS` | `512` | 最大生成 Token 数 |
| `LLM_TIMEOUT_SECONDS` | `30` | API 调用超时（秒） |

### Ollama 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_LLM_MODEL` | `qwen2.5:7b-instruct-q4_K_M` | Ollama LLM 模型 |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama Embedding 模型 |

### A/B 测试配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `AB_MODEL_A` | `qwen2.5:7b` | A 组模型 |
| `AB_MODEL_B` | `qwen2.5:3b` | B 组模型 |
| `AB_TRAFFIC_SPLIT` | `0.8` | A 组流量比例（0-1） |

### 限流配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `RATE_LIMIT_ENABLED` | `true` | 是否启用限流 |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | 每分钟最大请求数 |

### 可观测性配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `OTEL_ENABLED` | `false` | 是否启用 OpenTelemetry |
| `OTEL_EXPORTER_ENDPOINT` | `http://localhost:4317` | OTLP gRPC 导出端点 |
| `OTEL_SERVICE_NAME` | `rag-platform` | 服务名称（用于追踪标识） |

---

## 9. 故障排查

### 9.1 Ollama 连接被拒绝

**现象**：`ConnectionRefusedError: [Errno 111] Connection refused` 或 `httpx.ConnectError`

**排查步骤**：

```bash
# 1. 检查 Ollama 是否在运行
curl http://localhost:11434/api/tags

# 2. 本地模式：确认 Ollama 服务已启动
ollama serve

# 3. Docker 模式：检查容器状态
docker ps | grep ollama
docker logs rag-platform-ollama

# 4. K8s 模式：检查 Pod 和 Service
kubectl -n rag-platform get pod -l app=ollama
kubectl -n rag-platform logs -l app=ollama
kubectl -n rag-platform get svc ollama

# 5. 检查 .env 中 OLLAMA_BASE_URL 是否正确
# 本地：http://localhost:11434
# Docker Compose：http://ollama:11434
# K8s：http://ollama:11434
```

### 9.2 模型未找到

**现象**：`model 'xxx' not found` 或 `pull model manifest: file does not exist`

**排查步骤**：

```bash
# 1. 查看已下载模型
ollama list
# 或在容器中
docker exec -it rag-platform-ollama ollama list

# 2. 模型名称必须精确匹配
# 正确：qwen2.5:7b-instruct-q4_K_M
# 错误：qwen2.5-7b、qwen2.5:7b

# 3. 重新拉取模型
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama pull nomic-embed-text

# 4. 确认 .env 中的模型名与实际一致
grep OLLAMA .env
```

### 9.3 数据库迁移失败

**现象**：`alembic upgrade head` 报错

**排查步骤**：

```bash
# 1. 确认数据库连接可用
python -c "from app.core.config import settings; print(settings.database_url)"

# 2. SQLite 模式：确认 data 目录存在
mkdir -p data

# 3. PostgreSQL 模式：确认数据库已创建
psql -h localhost -U postgres -c "SELECT 1 FROM pg_database WHERE datname='rag_platform';"

# 4. 查看当前迁移版本
alembic current

# 5. 如果版本冲突，尝试回退重来
alembic downgrade base
alembic upgrade head

# 6. 如果 alembic_version 表损坏
# SQLite：删除 data/app.db 重新迁移
# PostgreSQL：DROP TABLE alembic_version; 然后重新迁移
```

### 9.4 Celery Worker 不处理任务

**现象**：文档上传后任务状态一直为 `PENDING`

**排查步骤**：

```bash
# 1. 确认不是 EAGER 模式（EAGER 模式不需要 Worker）
grep CELERY_TASK_ALWAYS_EAGER .env
# 如果为 true，任务会同步执行，不需要 Worker

# 2. 确认 Redis 可用
redis-cli ping
# 应返回 PONG

# 3. 启动 Worker
celery -A app.workers.celery_app.celery_app worker --loglevel=info

# 4. 检查 Worker 是否连接到正确的 Broker
# Worker 启动日志应显示：connected to redis://...

# 5. 查看任务队列状态
celery -A app.workers.celery_app.celery_app inspect active
celery -A app.workers.celery_app.celery_app inspect reserved

# 6. Docker 环境检查
docker logs rag-platform-worker

# 7. K8s 环境检查
kubectl -n rag-platform logs -l app=worker
```

### 9.5 限流过于激进

**现象**：正常请求频繁收到 `429 Too Many Requests`

**排查步骤**：

```bash
# 1. 查看当前限流配置
grep RATE_LIMIT .env

# 2. 临时关闭限流
# .env 中设置：
RATE_LIMIT_ENABLED=false

# 3. 或调高限流阈值
RATE_LIMIT_REQUESTS_PER_MINUTE=100

# 4. 重启服务使配置生效
# 本地：重启 uvicorn
# Docker：docker-compose restart api
# K8s：kubectl -n rag-platform rollout restart deployment/api
```

### 9.6 GPU 在 Kubernetes 中未检测到

**现象**：Ollama Pod 处于 `Pending` 状态，GPU 不可用

**排查步骤**：

```bash
# 1. 确认 nvidia-device-plugin 已部署
kubectl get pods -n kube-system | grep nvidia

# 2. 如果未部署，安装 nvidia-device-plugin
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

# 3. 确认节点有 GPU 资源
kubectl describe node <gpu-node-name> | grep nvidia.com/gpu
# 应显示：nvidia.com/gpu: 1（或更多）

# 4. 确认节点标签
kubectl get nodes --show-labels | grep gpu
# 如果缺少标签：
kubectl label nodes <gpu-node-name> gpu=true

# 5. 查看 Ollama Pod 事件
kubectl -n rag-platform describe pod -l app=ollama
# 查看 Events 部分，常见错误：
# - Insufficient nvidia.com/gpu：节点 GPU 已被其他 Pod 占用
# - FailedScheduling：没有满足 nodeSelector 的节点

# 6. 查看 GPU 使用情况
kubectl exec -it <gpu-node-pod> -- nvidia-smi

# 7. 如果无法解决 GPU 问题，可临时去掉 GPU 要求
# 编辑 ollama-deployment.yaml，删除：
#   nodeSelector:
#     gpu: "true"
#   resources:
#     limits:
#       nvidia.com/gpu: 1
# Ollama 将以 CPU 模式运行（性能较低但可用）
```

### 9.7 LanceDB 数据损坏

**现象**：查询报错 `ArrowInvalid` 或 `FileNotFoundError`

**排查步骤**：

```bash
# 1. 检查 LanceDB 数据目录
ls -la data/lancedb/

# 2. 如果数据损坏，删除并重建
rm -rf data/lancedb/
mkdir -p data/lancedb

# 3. 重新加载数据
python scripts/load_demo_docs.py

# 4. K8s 环境中，可能需要删除 PVC 并重建
# 注意：这会丢失所有向量数据
kubectl -n rag-platform delete pvc lancedb-pvc
kubectl apply -f k8s/lancedb-pvc.yaml
kubectl -n rag-platform rollout restart deployment/api deployment/worker
```
