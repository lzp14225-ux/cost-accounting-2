# API Gateway - 文件上传模块

## 功能说明

实现从文件上传到发送消息队列的完整流程：

1. **文件上传**：接收DWG/PRT文件
2. **文件验证**：检查文件类型、大小
3. **加密处理**：预留接口（第一期不实现）
4. **MinIO存储**：上传文件到对象存储
5. **数据库记录**：保存任务信息和审计日志
6. **消息队列**：发送任务消息到RabbitMQ
7. **事务回滚**：失败时自动回滚

## 目录结构

```
api-gateway/
├── main.py                 # FastAPI应用入口
├── auth.py                 # JWT认证
├── config.py               # 配置管理
├── routers/
│   └── jobs.py            # 文件上传接口
└── utils/
    ├── minio_client.py    # MinIO客户端
    ├── rabbitmq_client.py # RabbitMQ客户端
    ├── validators.py      # 文件验证
    └── encryption.py      # 加密解密（预留）
```

## 环境配置

### 1. 复制环境变量文件

```bash
cp .env.example .env
```

### 2. 修改 `.env` 文件

```env
# 数据库配置
DB_HOST=192.168.0.123
DB_PORT=5432
DB_NAME=mold_cost_db
DB_USER=root
DB_PASSWORD=yunzai123

# RabbitMQ配置
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=admin
RABBITMQ_PASSWORD=Admin@123

# MinIO配置
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# 文件上传配置
MAX_FILE_SIZE_MB=100
ALLOWED_FILE_EXTENSIONS=.dwg,.prt
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
# 开发模式（自动重载）
uvicorn api-gateway.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn api-gateway.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API接口

### 1. 文件上传

**接口**: `POST /api/v1/jobs/upload`

**请求头**:
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: multipart/form-data
```

**请求体**:
```
dwg_file: <DWG文件>（可选，但至少要有一个文件）
prt_file: <PRT文件>（可选）
encryption_key: <加密密钥>（可选，预留）
```

**响应示例**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "message": "文件上传成功，任务已创建，正在处理...",
  "files": {
    "dwg": {
      "filename": "mold_part_001.dwg",
      "size": 12345678
    },
    "prt": {
      "filename": "mold_part_001.prt",
      "size": 9876543
    }
  }
}
```

**错误响应**:
```json
{
  "error": "FILE_TOO_LARGE",
  "message": "文件大小超过限制",
  "max_size_mb": 100,
  "actual_size_bytes": 150000000
}
```

### 2. 查询任务状态

**接口**: `GET /api/v1/jobs/{job_id}/status`

**请求头**:
```
Authorization: Bearer <JWT_TOKEN>
```

**响应示例**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing",
  "current_stage": "cad_parsing",
  "progress": 20,
  "files": {
    "dwg": "mold_part_001.dwg",
    "prt": "mold_part_001.prt"
  },
  "total_cost": null,
  "created_at": "2026-01-12T10:00:00",
  "updated_at": "2026-01-12T10:01:00",
  "completed_at": null
}
```

## 测试

### 使用curl测试

```bash
# 1. 生成测试JWT token（开发环境）
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# 2. 上传文件
curl -X POST http://localhost:8000/api/v1/jobs/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "dwg_file=@test_files/mold_part_001.dwg" \
  -F "prt_file=@test_files/mold_part_001.prt"

# 3. 查询任务状态
curl -X GET http://localhost:8000/api/v1/jobs/{job_id}/status \
  -H "Authorization: Bearer $TOKEN"
```

### 使用Python测试

```python
import requests

# 1. 上传文件
url = "http://localhost:8000/api/v1/jobs/upload"
headers = {"Authorization": "Bearer YOUR_JWT_TOKEN"}
files = {
    "dwg_file": open("test_files/mold_part_001.dwg", "rb"),
    "prt_file": open("test_files/mold_part_001.prt", "rb")
}

response = requests.post(url, headers=headers, files=files)
print(response.json())

# 2. 查询状态
job_id = response.json()["job_id"]
status_url = f"http://localhost:8000/api/v1/jobs/{job_id}/status"
response = requests.get(status_url, headers=headers)
print(response.json())
```

## 数据流程

```
前端上传文件
    ↓
API网关接收（jobs.py）
    ↓
文件验证（validators.py）
    ├─ 检查扩展名
    ├─ 检查文件大小
    └─ 检查MIME类型
    ↓
加密处理（encryption.py）← 预留，第一期不实现
    ↓
上传到MinIO（minio_client.py）
    ├─ 生成file_id
    ├─ 构造object_name
    └─ 流式上传
    ↓
写入数据库（事务）
    ├─ 插入jobs表
    └─ 插入audit_logs表
    ↓
发送到RabbitMQ（rabbitmq_client.py）
    ├─ 队列：job_processing
    └─ 消息：{job_id, user_id}
    ↓
返回响应给前端
```

## 错误处理

### 1. 文件验证失败
- 文件类型不支持 → 400错误
- 文件过大 → 413错误
- 文件为空 → 400错误

### 2. MinIO上传失败
- 自动回滚（不创建数据库记录）
- 返回500错误

### 3. 数据库写入失败
- 自动回滚（删除MinIO中的文件）
- 返回500错误

### 4. RabbitMQ发送失败
- 不回滚数据库（任务已创建）
- 记录警告日志
- 可通过定时任务重新发送

## 监控指标

- 文件上传成功率
- 文件上传平均耗时
- MinIO上传失败次数
- 数据库写入失败次数
- RabbitMQ发送失败次数

## 注意事项

1. **JWT认证**：生产环境必须启用JWT认证
2. **文件大小**：默认限制100MB，可通过环境变量调整
3. **事务回滚**：确保数据一致性
4. **死信队列**：处理失败的消息
5. **日志记录**：所有操作都记录到audit_logs表

## 后续扩展

### 第二期功能
1. **加密解密**：实现encryption.py中的加密解密功能
2. **分片上传**：支持大文件分片上传
3. **断点续传**：支持上传中断后继续
4. **进度推送**：通过WebSocket推送上传进度

## 负责人

- **ZZH**：API网关、文件上传、认证鉴权、消息队列集成
