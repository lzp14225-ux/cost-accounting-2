# Docker 部署操作步骤

本文档说明 `mold_main` 项目如何使用 Docker 部署。当前项目包含前端、统一后端、MCP 服务、语音识别服务、文字转语音服务，并依赖 PostgreSQL、Redis、RabbitMQ、MinIO。

> 注意：项目中存在 `NXOpen` 相关脚本，这部分通常依赖 Siemens NX 的 Windows 环境和授权，普通 Linux Docker 容器不能直接运行。Docker 部署适合承载 Web/API、价格计算、MCP 等服务；真正依赖 NX 的功能建议继续放在 Windows 主机或独立 NX 服务中运行。

## 1. 服务划分

建议按以下服务拆分：

| 服务 | 说明 | 默认端口 |
| --- | --- | --- |
| `frontend` | React/Vite 构建后由 Nginx 提供静态页面 | `3000` |
| `backend` | FastAPI 统一后端，启动 `python main.py` | `8212` |
| `mcp` | CAD/价格 MCP 服务，启动 `mcp_services/cad_price_search_mcp/server.py` | `8201` |
| `speech` | Whisper 语音转文字服务，启动 `speech_services/main.py` | `8888` |
| `tts` | CosyVoice 文字转语音服务，启动 `tts_services/main.py` | `8890` |
| `postgres` | PostgreSQL 数据库 | `5432` |
| `redis` | Redis 缓存和消息推送 | `6379` |
| `rabbitmq` | RabbitMQ 队列 | `5672`、`15672` |
| `minio` | 文件对象存储 | `9000`、`9001` |

## 2. 新增 `.dockerignore`

在 `mold_main/.dockerignore` 中写入：

```dockerignore
.git
**/__pycache__
**/*.pyc
backend/logs
backend/output
backend/.env
mold_cost_account_react/node_modules
mold_cost_account_react/dist
```

## 3. 新增后端 Dockerfile

在 `mold_main/backend/Dockerfile` 中写入：

```dockerfile
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cu118

COPY . .

EXPOSE 8211

CMD ["python", "main.py"]
```

说明：

- 当前 `requirements.txt` 中有 `torch==2.6.0+cu118`，这是 CUDA 版本 wheel，普通 PyPI 源不一定能安装，所以 Dockerfile 里加了 PyTorch CUDA 源。
- 如果服务器没有 GPU，建议改成 CPU 版本 PyTorch，镜像会更小，安装也更稳定。

## 4. 新增前端 Nginx 配置

在 `mold_main/mold_cost_account_react/nginx.conf` 中写入：

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8212/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws {
        proxy_pass http://backend:8212/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

## 5. 新增前端 Dockerfile

在 `mold_main/mold_cost_account_react/Dockerfile` 中写入：

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
```

如果前端需要直接调用独立语音识别和 TTS 服务，构建前确认 `mold_cost_account_react/.env.production` 中的地址正确：

```env
VITE_API_BASE_URL=http://localhost:3000
VITE_AUTH_BASE_URL=http://localhost:3000
VITE_WS_BASE_URL=http://localhost:3000
VITE_SPEECH_RECOGNITION_BASE_URL=http://localhost:8888
VITE_TTS_BASE_URL=http://localhost:8890
```

如果部署到服务器，把 `localhost` 改成服务器 IP 或域名，例如 `http://192.168.3.61:8888`。

## 6. 新增 Docker 环境变量文件

在 `mold_main/backend/.env.docker` 中写入：

```env
PORT=8212
API_GATEWAY_HOST=0.0.0.0
DEBUG=false
RELOAD=false
LOG_LEVEL=INFO

DB_HOST=postgres
DB_PORT=5432
DB_NAME=mold_cost_db
DB_USER=postgres
DB_PASSWORD=postgres123

REDIS_URL=redis://redis:6379

RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=mold
RABBITMQ_PASSWORD=mold123

MINIO_ENDPOINT=minio:9000
MINIO_EXTERNAL_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_USE_HTTPS=false
MINIO_BUCKET_FILES=files

CAD_PRICE_SEARCH_MCP_URL=http://mcp:8201
CAD_PRICE_SEARCH_MCP_HOST=0.0.0.0
CAD_PRICE_SEARCH_MCP_PORT=8201

SPEECH_SERVICE_URL=http://speech:8888
SPEECH_HOST=0.0.0.0
SPEECH_PORT=8888
SPEECH_DEFAULT_MODEL=small
SPEECH_DEFAULT_LANGUAGE=zh
SPEECH_MODEL_DIR=/app/speech_services/models
FFMPEG_PATH=/usr/bin/ffmpeg

TTS_SERVICE_URL=http://tts:8890
TTS_HOST=0.0.0.0
TTS_PORT=8890
COSYVOICE_ROOT=/app/tts_services/CosyVoice
TTS_MODEL_DIR=/app/tts_services/CosyVoice/pretrained_models/CosyVoice-300M-SFT
TTS_DEFAULT_MODE=sft

START_EMBEDDED_WORKER=true
EMBEDDED_WORKER_ENTRY=workers/all_tasks_worker.py

CORS_ORIGINS=http://localhost:3000
JWT_SECRET_KEY=change-me
```

如果继续使用现有外部数据库、Redis、RabbitMQ、MinIO，把相关配置改成当前服务器地址，例如：

```env
DB_HOST=192.168.3.61
DB_PORT=5432
DB_NAME=mold_cost_db
DB_USER=postgres
DB_PASSWORD=你的数据库密码

REDIS_URL=redis://192.168.3.61:6379
RABBITMQ_HOST=192.168.3.61
RABBITMQ_PORT=5672
RABBITMQ_USER=你的 RabbitMQ 用户
RABBITMQ_PASSWORD=你的 RabbitMQ 密码
MINIO_ENDPOINT=192.168.3.61:9000
MINIO_EXTERNAL_ENDPOINT=192.168.3.61:9000
MINIO_ACCESS_KEY=你的 MinIO Access Key
MINIO_SECRET_KEY=你的 MinIO Secret Key
```

如果语音识别和 TTS 继续在宿主机独立启动，而不是放入 Docker，则保留宿主机地址：

```env
SPEECH_SERVICE_URL=http://192.168.3.61:8888
TTS_SERVICE_URL=http://192.168.3.61:8890
```

## 7. 新增 `docker-compose.yml`

在 `mold_main/docker-compose.yml` 中写入：

```yaml
services:
  postgres:
    image: postgres:16
    container_name: mold_postgres
    environment:
      POSTGRES_DB: mold_cost_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres123
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    container_name: mold_redis
    ports:
      - "6379:6379"

  rabbitmq:
    image: rabbitmq:3-management
    container_name: mold_rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: mold
      RABBITMQ_DEFAULT_PASS: mold123
    ports:
      - "5672:5672"
      - "15672:15672"

  minio:
    image: minio/minio
    container_name: mold_minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

  backend:
    build:
      context: ./backend
    container_name: mold_backend
    env_file:
      - ./backend/.env.docker
    ports:
      - "8212:8212"
    volumes:
      - ./backend/logs:/app/logs
      - ./backend/output:/app/output
    depends_on:
      - postgres
      - redis
      - rabbitmq
      - minio

  mcp:
    build:
      context: ./backend
    container_name: mold_mcp
    command: ["python", "mcp_services/cad_price_search_mcp/server.py"]
    env_file:
      - ./backend/.env.docker
    ports:
      - "8201:8201"
    volumes:
      - ./backend/logs:/app/logs
      - ./backend/output:/app/output
    depends_on:
      - postgres
      - redis
      - rabbitmq
      - minio

  speech:
    build:
      context: ./backend
    container_name: mold_speech
    command: ["python", "speech_services/main.py"]
    env_file:
      - ./backend/.env.docker
    ports:
      - "8888:8888"
    volumes:
      - ./backend/speech_services/audio:/app/speech_services/audio
      - ./backend/speech_services/models:/app/speech_services/models

  tts:
    build:
      context: ./backend
    container_name: mold_tts
    command: ["python", "tts_services/main.py"]
    env_file:
      - ./backend/.env.docker
    ports:
      - "8890:8890"
    volumes:
      - ./backend/tts_services/audio:/app/tts_services/audio
      - ./backend/tts_services/CosyVoice/pretrained_models:/app/tts_services/CosyVoice/pretrained_models

  frontend:
    build:
      context: ./mold_cost_account_react
    container_name: mold_frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

volumes:
  postgres_data:
  minio_data:
```

## 8. 启动服务

进入项目根目录：

```powershell
cd D:\AI\Pycharm\chengben2\mold_main
```

首次在新电脑部署时，建议先创建运行期目录。虽然 Docker 在绑定挂载时通常会自动创建缺失目录，但手动创建可以避免 Windows Docker Desktop 的路径和权限问题：

```powershell
mkdir .\backend\logs
mkdir .\backend\output
mkdir .\backend\speech_services\audio
mkdir .\backend\speech_services\models
mkdir .\backend\tts_services\audio
mkdir .\backend\tts_services\CosyVoice\pretrained_models
```

这些目录的用途：

| 宿主机目录 | 容器内目录 | 用途 |
| --- | --- | --- |
| `backend/logs` | `/app/logs` | 后端、MCP 等服务日志 |
| `backend/output` | `/app/output` | 任务输出、中间文件 |
| `backend/speech_services/audio` | `/app/speech_services/audio` | 语音识别上传和临时音频 |
| `backend/speech_services/models` | `/app/speech_services/models` | Whisper 模型缓存 |
| `backend/tts_services/audio` | `/app/tts_services/audio` | TTS 生成的音频缓存 |
| `backend/tts_services/CosyVoice/pretrained_models` | `/app/tts_services/CosyVoice/pretrained_models` | CosyVoice 模型目录 |

构建并启动：

```powershell
docker compose up -d --build
```

查看运行状态：

```powershell
docker compose ps
```

查看日志：

```powershell
docker compose logs -f backend
docker compose logs -f mcp
docker compose logs -f speech
docker compose logs -f tts
```

## 9. 访问地址

| 地址 | 说明 |
| --- | --- |
| `http://localhost:3000` | 前端页面 |
| `http://localhost:8212/health` | 后端健康检查 |
| `http://localhost:8201/health` | MCP 健康检查 |
| `http://localhost:8888/api/speech/health` | 语音识别服务健康检查 |
| `http://localhost:8890/api/tts/health` | TTS 服务健康检查 |
| `http://localhost:15672` | RabbitMQ 管理台 |
| `http://localhost:9001` | MinIO 控制台 |

RabbitMQ 默认账号密码：

```text
mold / mold123
```

MinIO 默认账号密码：

```text
minioadmin / minioadmin123
```

## 10. 数据库迁移

如果第一阶段继续使用外部 PostgreSQL，可以跳过本节。

如果要把现有数据库迁进 Docker，先从旧库导出：

```powershell
pg_dump -h 192.168.3.61 -U postgres -d mold_cost_db -f mold_cost_db.sql
```

复制到 PostgreSQL 容器：

```powershell
docker cp mold_cost_db.sql mold_postgres:/mold_cost_db.sql
```

导入容器数据库：

```powershell
docker exec -it mold_postgres psql -U postgres -d mold_cost_db -f /mold_cost_db.sql
```

导入后把 `backend/.env.docker` 的数据库配置切回容器内部地址：

```env
DB_HOST=postgres
DB_PORT=5432
DB_NAME=mold_cost_db
DB_USER=postgres
DB_PASSWORD=postgres123
```

然后重启后端、MCP、语音识别和 TTS：

```powershell
docker compose restart backend mcp speech tts
```

## 11. 常用维护命令

停止服务：

```powershell
docker compose down
```

停止并删除数据卷：

```powershell
docker compose down -v
```

重新构建某个服务：

```powershell
docker compose build backend
docker compose up -d backend
```

重新构建语音识别或 TTS 服务：

```powershell
docker compose build speech tts
docker compose up -d speech tts
```

进入后端容器：

```powershell
docker exec -it mold_backend sh
```

查看后端最近日志：

```powershell
docker compose logs --tail=200 backend
```

## 12. 推荐落地顺序

1. 先只容器化 `frontend`、`backend`、`mcp`，数据库、Redis、RabbitMQ、MinIO 继续连现有 `192.168.3.61`。
2. 确认 `http://localhost:8212/health` 和 `http://localhost:8201/health` 正常。
3. 再容器化 `speech` 和 `tts`，确认 `http://localhost:8888/api/speech/health`、`http://localhost:8890/api/tts/health` 正常。
4. 确认前端上传、任务处理、WebSocket 进度推送、语音转文字、文字转语音正常。
5. 再迁移 PostgreSQL 和 MinIO 数据到容器。
6. 最后处理 NXOpen 相关功能，把它作为独立 Windows 服务或外部调用服务接入。

## 13. 本机独立启动语音服务

如果语音识别和 TTS 不放进 Docker，而是按当前 `.env` 在宿主机独立启动，可以在 `mold_main/backend` 目录执行：

```powershell
python speech_services/main.py
```

另开一个终端：

```powershell
python tts_services/main.py
```

对应访问地址：

```text
语音识别：http://192.168.3.61:8888
TTS：http://192.168.3.61:8890
```

这种方式下，Docker 里的 `backend` 只需要通过 `SPEECH_SERVICE_URL` 和 `TTS_SERVICE_URL` 调用宿主机服务即可，不需要启动 compose 里的 `speech`、`tts` 服务。

## 14. 新电脑部署检查清单

新电脑通常缺少运行环境、模型文件、数据库数据和外部服务配置。正式启动前按下面顺序检查。

### 14.1 必装软件

| 软件 | 用途 | 检查命令 |
| --- | --- | --- |
| Docker Desktop | 运行容器和 compose | `docker version` |
| Docker Compose v2 | 编排服务 | `docker compose version` |
| Git | 拉取代码 | `git --version` |
| PowerShell | 执行 Windows 命令 | 系统自带 |
| PostgreSQL 客户端 | 导入导出数据库，可选 | `pg_dump --version` |

如果 `docker` 命令不可用，先确认 Docker Desktop 已启动，并且 Windows 已启用 WSL2。

### 14.2 端口占用

本项目默认会用到这些端口：

| 端口 | 服务 |
| --- | --- |
| `3000` | 前端 |
| `8212` | 后端 |
| `8201` | MCP |
| `8888` | 语音识别 |
| `8890` | TTS |
| `5432` | PostgreSQL |
| `6379` | Redis |
| `5672` | RabbitMQ |
| `15672` | RabbitMQ 管理台 |
| `9000` | MinIO API |
| `9001` | MinIO 控制台 |

检查端口占用：

```powershell
netstat -ano | findstr ":8212"
netstat -ano | findstr ":8201"
netstat -ano | findstr ":8888"
netstat -ano | findstr ":8890"
```

如果端口被占用，要么停止占用进程，要么修改 `docker-compose.yml` 左侧宿主机端口。例如：

```yaml
ports:
  - "8213:8212"
```

### 14.3 环境变量文件

确认存在：

```text
mold_main/backend/.env.docker
mold_main/mold_cost_account_react/.env.production
```

重点检查：

| 变量 | 说明 |
| --- | --- |
| `DB_HOST` | 数据库地址，容器内数据库用 `postgres`，外部数据库用真实 IP |
| `REDIS_URL` | Redis 地址，容器内用 `redis://redis:6379` |
| `RABBITMQ_HOST` | RabbitMQ 地址，容器内用 `rabbitmq` |
| `MINIO_ENDPOINT` | MinIO 内部访问地址，容器内用 `minio:9000` |
| `MINIO_EXTERNAL_ENDPOINT` | 前端或外部访问 MinIO 的地址 |
| `CAD_PRICE_SEARCH_MCP_URL` | 后端调用 MCP 的地址，容器内用 `http://mcp:8201` |
| `SPEECH_SERVICE_URL` | 后端调用语音识别服务地址 |
| `TTS_SERVICE_URL` | 后端调用 TTS 服务地址 |
| `JWT_SECRET_KEY` | 生产环境必须改成随机强密钥 |

### 14.4 模型文件

语音识别和 TTS 依赖模型文件。新电脑如果没有模型，服务可能启动慢，或者直接启动失败。

Whisper 模型缓存目录：

```text
backend/speech_services/models
```

CosyVoice 模型目录：

```text
backend/tts_services/CosyVoice/pretrained_models/CosyVoice-300M-SFT
```

如果 TTS 启动时报错：

```text
CosyVoice model dir not found
```

说明 `TTS_MODEL_DIR` 指向的模型目录不存在，需要把模型文件复制到：

```text
backend/tts_services/CosyVoice/pretrained_models/CosyVoice-300M-SFT
```

### 14.5 数据库数据

新电脑上的 PostgreSQL 是空库时，后端能启动但业务接口可能报表不存在或查不到数据。

如果使用外部数据库，`.env.docker` 指向外部 IP 即可。

如果使用容器数据库，需要导入旧数据库备份，见“10. 数据库迁移”。

### 14.6 MinIO 桶和文件

新 MinIO 没有 bucket 和历史文件。至少要确认文件桶存在：

```text
files
```

可以访问 MinIO 控制台：

```text
http://localhost:9001
```

登录后手动创建 `files` bucket。若历史任务依赖旧 MinIO 文件，还需要迁移对象数据。

### 14.7 GPU 与 CPU

当前 `requirements.txt` 使用：

```text
torch==2.6.0+cu118
```

这适合 CUDA 11.8 相关环境，但新电脑如果没有 NVIDIA GPU 或没有配置 Docker GPU 支持，语音识别和 TTS 会退回 CPU 或安装失败。

如果只用 CPU，建议改成 CPU 版 PyTorch，并去掉 Dockerfile 中 CUDA wheel 源的依赖。

如果要在 Docker 中使用 GPU，需要额外安装：

```text
NVIDIA Driver
NVIDIA Container Toolkit
```

并在 compose 的 `speech`、`tts` 服务中增加 GPU 配置。没有配置 GPU 时，不要假设容器能直接访问显卡。

### 14.8 NXOpen 功能

`NXOpen` 依赖 Siemens NX 本机环境和授权。新电脑如果没有安装 NX，相关脚本不能正常运行。

普通 Linux Docker 容器通常不能直接运行 NXOpen。推荐方式：

1. Docker 部署 Web/API/MCP/语音/TTS。
2. NXOpen 相关脚本继续放 Windows 主机运行。
3. 后端通过接口或任务队列调用 Windows 主机上的 NX 服务。

## 15. 常见问题排查

### 15.1 `docker compose up -d --build` 拉取镜像失败

常见原因是网络或镜像源访问慢。

处理方式：

1. 确认 Docker Desktop 能正常访问网络。
2. 给 Docker Desktop 配置可用的 registry mirror。
3. 重新执行：

```powershell
docker compose pull
docker compose up -d --build
```

### 15.2 `pip install` 安装 PyTorch 失败

常见原因：

- `torch==2.6.0+cu118` 需要 PyTorch CUDA wheel 源。
- 网络无法访问 `download.pytorch.org`。
- 当前平台没有匹配 wheel。

处理方式：

1. 确认 Dockerfile 中包含：

```dockerfile
--extra-index-url https://download.pytorch.org/whl/cu118
```

2. 如果不需要 GPU，改成 CPU 版本 PyTorch。
3. 如果网络受限，先在可联网环境构建镜像，再导出镜像迁移。

### 15.3 后端健康检查不通

检查：

```powershell
docker compose ps
docker compose logs -f backend
```

重点看：

- `.env.docker` 是否存在。
- `PORT` 是否是 `8212`。
- `DB_HOST`、`REDIS_URL`、`RABBITMQ_HOST` 是否能访问。
- 宿主机端口 `8212` 是否被占用。

健康检查地址：

```text
http://localhost:8212/health
```

### 15.4 MCP 健康检查不通

检查：

```powershell
docker compose logs -f mcp
```

确认：

```env
CAD_PRICE_SEARCH_MCP_HOST=0.0.0.0
CAD_PRICE_SEARCH_MCP_PORT=8201
CAD_PRICE_SEARCH_MCP_URL=http://mcp:8201
```

健康检查地址：

```text
http://localhost:8201/health
```

### 15.5 语音识别服务启动慢

第一次启动会加载或下载 Whisper 模型，耗时较长。模型默认缓存到：

```text
backend/speech_services/models
```

查看日志：

```powershell
docker compose logs -f speech
```

如果无法下载模型，需要手动准备模型缓存，或让服务能访问外网。

### 15.6 TTS 服务启动失败

常见报错：

```text
CosyVoice root not found
CosyVoice model dir not found
```

检查：

```env
COSYVOICE_ROOT=/app/tts_services/CosyVoice
TTS_MODEL_DIR=/app/tts_services/CosyVoice/pretrained_models/CosyVoice-300M-SFT
```

并确认宿主机目录存在：

```text
backend/tts_services/CosyVoice/pretrained_models/CosyVoice-300M-SFT
```

### 15.7 前端页面能打开，但接口请求失败

检查 `mold_cost_account_react/.env.production`：

```env
VITE_API_BASE_URL=http://localhost:3000
VITE_AUTH_BASE_URL=http://localhost:3000
VITE_WS_BASE_URL=http://localhost:3000
VITE_SPEECH_RECOGNITION_BASE_URL=http://localhost:8888
VITE_TTS_BASE_URL=http://localhost:8890
```

如果部署到服务器，不能继续使用 `localhost` 给其他电脑访问，要改成服务器 IP 或域名。

同时检查 Nginx 是否正确反代 `/api` 和 `/ws` 到 `backend:8212`。

### 15.8 WebSocket 连接失败

检查：

- 前端 `VITE_WS_BASE_URL` 是否正确。
- Nginx 是否包含 `Upgrade` 和 `Connection` 头。
- 后端 Redis 是否连接成功。

查看日志：

```powershell
docker compose logs -f backend
docker compose logs -f redis
```

### 15.9 数据库连接失败

如果使用容器数据库：

```env
DB_HOST=postgres
DB_PORT=5432
```

如果使用外部数据库：

```env
DB_HOST=192.168.3.61
DB_PORT=5432
```

检查外部数据库防火墙是否允许新电脑或 Docker 所在主机访问 `5432`。

### 15.10 RabbitMQ 连接失败

检查管理台：

```text
http://localhost:15672
```

确认 `.env.docker`：

```env
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=mold
RABBITMQ_PASSWORD=mold123
```

如果使用外部 RabbitMQ，改成外部 IP、账号和密码。

### 15.11 MinIO 上传或下载失败

检查：

```env
MINIO_ENDPOINT=minio:9000
MINIO_EXTERNAL_ENDPOINT=http://localhost:9000
MINIO_BUCKET_FILES=files
```

容器内部访问用 `minio:9000`，浏览器或外部访问用 `localhost:9000` 或服务器 IP。

如果报 bucket 不存在，到 MinIO 控制台创建 `files`。

### 15.12 日志目录没有文件

确认 compose 中有挂载：

```yaml
volumes:
  - ./backend/logs:/app/logs
```

宿主机日志目录：

```text
backend/logs
```

容器内日志目录：

```text
/app/logs
```

如果目录不存在，先按“8. 启动服务”中的命令创建运行期目录。

### 15.13 修改配置后没有生效

如果只改了 `.env.docker`：

```powershell
docker compose restart backend mcp speech tts
```

如果改了 Dockerfile、requirements、前端代码：

```powershell
docker compose up -d --build
```

如果改了前端 `.env.production`，必须重新构建前端镜像，因为 Vite 的环境变量在构建阶段写入静态文件。

### 15.14 清理并重来

只停止服务：

```powershell
docker compose down
```

停止并删除数据库、MinIO 等数据卷：

```powershell
docker compose down -v
```

注意：`down -v` 会删除容器数据库和 MinIO 数据，新电脑测试可以用，生产环境谨慎使用。
