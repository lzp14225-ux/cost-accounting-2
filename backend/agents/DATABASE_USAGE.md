# InteractionAgent 和 LangGraph 数据库使用说明

## 🎯 核心结论

**InteractionAgent 和 LangGraph 不会自动创建任何数据库表！**

## 📋 详细说明

### 1. InteractionAgent 的数据存储

InteractionAgent 是一个**纯内存**的业务逻辑组件，它：

✅ **不会创建数据库表**
✅ **不会直接操作数据库**
✅ **只在内存中处理数据**

```python
# InteractionAgent 只做这些事情：
class InteractionAgent:
    def __init__(self, use_llm: bool = False):
        # 1. 初始化 LLM（可选）
        # 2. 构建 LangGraph 工作流
        # 没有任何数据库连接！
    
    async def process(self, context: Dict) -> OpResult:
        # 1. 检查参数
        # 2. 生成提示
        # 3. 返回结果
        # 全部在内存中完成！
```

### 2. LangGraph 的数据持久化

LangGraph 框架本身**默认不使用数据库**，但它提供了可选的持久化功能。

#### 默认行为（我们当前使用的）

```python
# 当前实现 - 无持久化
workflow = StateGraph(InteractionState)
workflow.add_node("check_params", self._check_params_node)
# ...
graph = workflow.compile()  # ✅ 纯内存，不创建表
```

**特点**：
- ✅ 状态只在内存中
- ✅ 不需要数据库
- ✅ 重启后状态丢失（这是预期的）

#### 可选的持久化（我们没有启用）

如果需要持久化，LangGraph 支持使用 Checkpointer：

```python
# 这是可选的，我们没有使用！
from langgraph.checkpoint.postgres import PostgresSaver

# 需要显式配置才会创建表
checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost/db"
)

graph = workflow.compile(checkpointer=checkpointer)
# ⚠️ 只有这样才会创建表！
```

**如果启用了 Checkpointer，会创建这些表**：
- `checkpoints` - 存储工作流状态快照
- `checkpoint_writes` - 存储状态写入记录

**但我们没有启用，所以不会创建这些表！**

### 3. 我们的数据库表

我们的系统使用的数据库表都是**手动定义**的，与 LangGraph 无关：

#### 已有的表（由 Alembic 迁移创建）

```sql
-- 任务表
CREATE TABLE jobs (
    job_id UUID PRIMARY KEY,
    user_id VARCHAR(255),
    status VARCHAR(50),
    current_stage VARCHAR(100),
    progress INTEGER,
    ...
);

-- 交互记录表（用于保存用户输入）
CREATE TABLE interaction_cards (
    interaction_id UUID PRIMARY KEY,
    job_id UUID,
    card_id UUID,
    card_type VARCHAR(50),
    card_data JSONB,
    status VARCHAR(50),
    ...
);

-- 用户响应表
CREATE TABLE user_responses (
    response_id UUID PRIMARY KEY,
    interaction_id UUID,
    job_id UUID,
    action VARCHAR(50),
    inputs JSONB,
    ...
);

-- 价格快照表
CREATE TABLE price_snapshots (...);

-- 工艺规则快照表
CREATE TABLE process_snapshots (...);

-- 审计日志表
CREATE TABLE audit_logs (...);
```

这些表都是我们自己定义的，不是 LangGraph 创建的！

### 4. 数据流转示意图

```
┌─────────────────────────────────────────────────┐
│  InteractionAgent (纯内存)                      │
│  ┌──────────────────────────────────────┐      │
│  │ 1. 接收 context (内存数据)           │      │
│  │ 2. 检查参数 (内存操作)               │      │
│  │ 3. 生成提示 (内存操作)               │      │
│  │ 4. 返回 OpResult (内存数据)          │      │
│  └──────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Orchestrator (内存 + 可选持久化)               │
│  ┌──────────────────────────────────────┐      │
│  │ 1. 调用 InteractionAgent             │      │
│  │ 2. 获取结果 (内存)                   │      │
│  │ 3. 决定下一步 (内存)                 │      │
│  └──────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  API Gateway (负责数据库持久化)                 │
│  ┌──────────────────────────────────────┐      │
│  │ 1. 保存交互记录到 interaction_cards  │      │
│  │ 2. 保存用户输入到 user_responses     │      │
│  │ 3. 更新任务状态到 jobs               │      │
│  └──────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
                    ↓
              PostgreSQL
```

### 5. 实际的数据持久化流程

#### 场景：用户补充参数

```python
# 1. InteractionAgent 检查参数（内存）
result = await interaction_agent.process({
    "job_id": "uuid",
    "features": [...]
})

# 2. Orchestrator 推送交互需求（内存 -> Redis）
await redis_client.publish(
    f"job:{job_id}:interaction",
    json.dumps(result.data)
)

# 3. 用户提交参数（HTTP -> 数据库）
POST /api/v1/jobs/{job_id}/submit
{
    "inputs": {"UP01.thickness_mm": 30}
}

# 4. API Gateway 保存到数据库
await interaction_repo.save_user_response(
    db=db,  # PostgreSQL 连接
    job_id=job_id,
    inputs=inputs
)

# 5. 恢复工作流时，从数据库读取
user_input = await interaction_repo.get_user_input(db, job_id)

# 6. 再次调用 InteractionAgent（内存）
result = await interaction_agent.process({
    "job_id": job_id,
    "features": features,
    "user_input": user_input  # 从数据库读取的
})
```

### 6. 如何验证

#### 检查当前数据库表

```sql
-- 连接到数据库
psql -U postgres -d moldcost

-- 查看所有表
\dt

-- 你会看到：
-- jobs
-- interaction_cards
-- user_responses
-- price_snapshots
-- process_snapshots
-- audit_logs
-- alembic_version

-- 不会看到：
-- checkpoints (LangGraph 的表)
-- checkpoint_writes (LangGraph 的表)
```

#### 检查代码

```bash
# 搜索 checkpointer 相关代码
grep -r "checkpointer" moldCost/agents/
# 结果：无匹配（证明我们没有使用）

# 搜索 PostgresSaver
grep -r "PostgresSaver" moldCost/agents/
# 结果：无匹配（证明我们没有使用）
```

### 7. 总结对比

| 组件 | 数据存储 | 创建表 | 说明 |
|------|---------|--------|------|
| InteractionAgent | 内存 | ❌ 否 | 纯业务逻辑 |
| LangGraph (默认) | 内存 | ❌ 否 | 我们使用的模式 |
| LangGraph (Checkpointer) | 数据库 | ✅ 是 | 我们没有启用 |
| API Gateway | 数据库 | ✅ 是 | 我们自己的表 |

### 8. 如果需要持久化 LangGraph 状态

如果将来需要持久化工作流状态（例如支持长时间运行的任务），可以这样做：

```python
# 1. 安装依赖
pip install langgraph-checkpoint-postgres

# 2. 修改 Orchestrator
from langgraph.checkpoint.postgres import PostgresSaver

class OrchestratorAgent:
    def __init__(self):
        # 配置 checkpointer
        checkpointer = PostgresSaver.from_conn_string(
            os.getenv("DATABASE_URL")
        )
        
        # 编译时传入
        self.workflow = self._build_workflow().compile(
            checkpointer=checkpointer
        )

# 3. 运行迁移创建表
# LangGraph 会自动创建 checkpoints 和 checkpoint_writes 表
```

**但目前我们不需要这样做！**

### 9. 最佳实践建议

#### 当前架构（推荐）

✅ **InteractionAgent**: 纯内存，无状态
✅ **LangGraph**: 纯内存，无持久化
✅ **API Gateway**: 负责所有数据库操作

**优点**：
- 简单清晰
- 性能高
- 易于测试
- 无额外表

#### 如果需要持久化

只在以下情况考虑启用 LangGraph Checkpointer：
- 任务运行时间 > 1小时
- 需要支持服务重启后恢复
- 需要回溯工作流历史

**但对于我们的场景（模具报价），当前架构已经足够！**

---

## 🎯 最终答案

**不会！InteractionAgent 和 LangGraph 不会在数据库创建任何表！**

所有数据库表都是我们通过 Alembic 迁移手动创建的，与 LangGraph 框架无关。

---

**版本**: 1.0.0  
**更新日期**: 2024-01-15  
**负责人**: 人员B2
