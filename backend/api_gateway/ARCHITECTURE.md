# API Gateway 三层架构说明

## 架构概览

本项目采用经典的三层架构模式，将代码按职责分为三层：

```
api-gateway/
├── routers/          # Controller层 - 处理HTTP请求和响应
├── services/         # Service层 - 业务逻辑处理
├── repositories/     # Repository层 - 数据访问
└── utils/           # 工具类 - 通用功能（MinIO、RabbitMQ等）
```

## 各层职责

### 1. Controller层 (routers/)

**职责：**
- 接收HTTP请求
- 参数验证和转换
- 调用Service层处理业务
- 返回HTTP响应
- 异常处理和错误响应

**特点：**
- 薄层，不包含业务逻辑
- 只负责请求/响应的转换
- 依赖注入（数据库会话、当前用户等）

**示例：**
```python
@router.post("/upload")
async def upload_files(
    dwg_file: Optional[UploadFile] = File(None),
    prt_file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    job_service = JobService()
    result = await job_service.create_job_from_upload(
        db=db,
        user_id=current_user["user_id"],
        dwg_file=dwg_file,
        prt_file=prt_file
    )
    return result
```

### 2. Service层 (services/)

**职责：**
- 实现核心业务逻辑
- 协调多个Repository
- 事务管理
- 调用外部服务（MinIO、RabbitMQ）
- 业务规则验证

**特点：**
- 包含完整的业务流程
- 可复用的业务逻辑
- 独立于HTTP层，可用于其他场景（CLI、定时任务等）

**示例：**
```python
class JobService:
    async def create_job_from_upload(self, db, user_id, dwg_file, prt_file):
        # 1. 验证文件
        # 2. 上传到MinIO
        # 3. 数据库事务
        #    - 创建任务
        #    - 创建快照
        #    - 记录审计日志
        # 4. 发送消息到RabbitMQ
        # 5. 返回结果
```

### 3. Repository层 (repositories/)

**职责：**
- 数据库CRUD操作
- SQL查询封装
- 数据持久化

**特点：**
- 只负责数据访问
- 不包含业务逻辑
- 可测试性强（易于Mock）

**示例：**
```python
class JobRepository:
    @staticmethod
    async def create_job(db, job_id, user_id, dwg_info, prt_info):
        sql = text("INSERT INTO jobs (...) VALUES (...)")
        await db.execute(sql, {...})
```

## 数据流向

```
HTTP请求
    ↓
Controller (routers/jobs.py)
    ↓
Service (services/job_service.py)
    ↓
Repository (repositories/job_repository.py)
    ↓
Database
```

## 依赖关系

- **Controller** → **Service** → **Repository**
- 上层可以调用下层，下层不能调用上层
- 同层之间可以相互调用（如Service之间）

## 优势

1. **职责清晰**：每层只关注自己的职责
2. **易于测试**：可以单独测试每一层
3. **可维护性**：修改某一层不影响其他层
4. **可复用性**：Service层可在多个Controller中复用
5. **易于扩展**：添加新功能只需在对应层添加代码

## 文件对应关系

### Controller层
- `routers/jobs.py` - 任务相关的HTTP接口

### Service层
- `services/job_service.py` - 任务业务逻辑

### Repository层
- `repositories/job_repository.py` - 任务数据访问
- `repositories/audit_repository.py` - 审计日志数据访问
- `repositories/snapshot_repository.py` - 快照数据访问

### 工具层
- `utils/minio_client.py` - MinIO文件存储
- `utils/rabbitmq_client.py` - RabbitMQ消息队列
- `utils/validators.py` - 文件验证
- `utils/encryption.py` - 加密处理

## 使用示例

### 添加新接口

1. **在Repository层添加数据访问方法**
```python
# repositories/job_repository.py
async def get_jobs_by_user(db: AsyncSession, user_id: str):
    sql = text("SELECT * FROM jobs WHERE user_id = :user_id")
    result = await db.execute(sql, {"user_id": user_id})
    return result.fetchall()
```

2. **在Service层添加业务逻辑**
```python
# services/job_service.py
async def list_user_jobs(self, db: AsyncSession, user_id: str):
    jobs = await self.job_repo.get_jobs_by_user(db, user_id)
    # 处理业务逻辑
    return {"jobs": jobs}
```

3. **在Controller层添加HTTP接口**
```python
# routers/jobs.py
@router.get("/")
async def list_jobs(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    job_service = JobService()
    return await job_service.list_user_jobs(db, current_user["user_id"])
```

## 注意事项

1. **不要跨层调用**：Controller不应直接调用Repository
2. **事务管理在Service层**：使用`async with db.begin()`
3. **异常处理**：Service抛出业务异常，Controller转换为HTTP响应
4. **日志记录**：每层都应记录适当的日志
5. **依赖注入**：通过构造函数或方法参数传递依赖
