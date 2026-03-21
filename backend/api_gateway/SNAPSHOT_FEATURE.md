# 快照功能说明

## 功能概述

在创建任务时，系统会自动将 `price_items` 和 `process_rules` 表的数据复制到对应的快照表中，实现**价格版本锁定**和**规则版本锁定**。

## 为什么需要快照？

### 1. **价格版本锁定**
- 任务创建时的价格，后续价格变更不影响已创建的任务
- 用户可以修改快照中的价格，不影响原始价格库
- 可以追溯任务使用的价格版本

### 2. **规则版本锁定**
- 任务创建时的工艺规则，后续规则变更不影响已创建的任务
- 用户可以修改快照中的规则，不影响原始规则库
- 可以追溯任务使用的规则版本

### 3. **审计追溯**
- 完整记录任务使用的价格和规则
- 支持重算时使用相同的价格和规则
- 符合财务审计要求

## 数据流程

```
任务创建
    ↓
写入jobs表
    ↓
创建快照（事务中）
    ├─ price_items → job_price_snapshots
    └─ process_rules → job_process_snapshots
    ↓
快照与job_id关联
    ↓
后续Agent使用快照数据
```

## 表结构

### job_price_snapshots（价格快照表）

```sql
CREATE TABLE job_price_snapshots (
    snapshot_id UUID PRIMARY KEY,
    job_id UUID NOT NULL,  -- 关联jobs表
    original_price_id VARCHAR(50),  -- 原price_items的ID
    feature_type VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    unit_price DECIMAL(10,4) NOT NULL,  -- 用户可修改
    unit VARCHAR(20) NOT NULL,
    param_conditions JSONB,
    priority INTEGER DEFAULT 0,
    is_modified BOOLEAN DEFAULT false,  -- 是否被用户修改
    modified_at TIMESTAMP,
    modified_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
```

### job_process_snapshots（工艺规则快照表）

```sql
CREATE TABLE job_process_snapshots (
    snapshot_id UUID PRIMARY KEY,
    job_id UUID NOT NULL,  -- 关联jobs表
    original_rule_id VARCHAR(50),  -- 原process_rules的ID
    feature_type VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    conditions JSONB NOT NULL,  -- 用户可修改
    output_params JSONB NOT NULL,  -- 用户可修改
    priority INTEGER DEFAULT 0,
    is_modified BOOLEAN DEFAULT false,  -- 是否被用户修改
    modified_at TIMESTAMP,
    modified_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
```

## 实现代码

### 1. 快照管理器（utils/snapshot_manager.py）

```python
from ..utils.snapshot_manager import SnapshotManager

# 创建所有快照
snapshot_stats = await SnapshotManager.create_all_snapshots(db, job_id)
# 返回: {"price_items_count": 50, "process_rules_count": 30, "total_count": 80}

# 查询价格快照
price_snapshots = await SnapshotManager.get_price_snapshots(db, job_id)

# 查询工艺规则快照
process_snapshots = await SnapshotManager.get_process_snapshots(db, job_id)

# 更新价格快照（用户修改）
await SnapshotManager.update_price_snapshot(
    db, snapshot_id, unit_price=0.06, modified_by="user_123"
)

# 更新工艺规则快照（用户修改）
await SnapshotManager.update_process_snapshot(
    db, snapshot_id, conditions={...}, output_params={...}, modified_by="user_123"
)
```

### 2. 文件上传时自动创建快照（routers/jobs.py）

```python
async with db.begin():
    # 1. 插入jobs表
    await db.execute(insert_job_sql, {...})
    
    # 2. 创建快照（自动）
    snapshot_stats = await create_snapshots_for_job(db, job_id)
    # 返回: {"price_items_count": 50, "process_rules_count": 30}
    
    # 3. 插入audit_logs表
    await db.execute(insert_audit_sql, {...})
```

## API接口

### 1. 查询价格快照

```bash
GET /api/v1/jobs/{job_id}/snapshots/prices
Authorization: Bearer <JWT_TOKEN>

Response:
{
  "job_id": "uuid",
  "count": 50,
  "snapshots": [
    {
      "snapshot_id": "uuid",
      "original_price_id": "P001",
      "feature_type": "WIRE",
      "name": "慢丝线割-厚度10-50mm",
      "unit_price": 0.05,
      "unit": "元/mm²",
      "param_conditions": {...},
      "priority": 10,
      "is_modified": false,
      "created_at": "2026-01-12T10:00:00"
    },
    ...
  ]
}
```

### 2. 查询工艺规则快照

```bash
GET /api/v1/jobs/{job_id}/snapshots/processes
Authorization: Bearer <JWT_TOKEN>

Response:
{
  "job_id": "uuid",
  "count": 30,
  "snapshots": [
    {
      "snapshot_id": "uuid",
      "original_rule_id": "R001",
      "feature_type": "WIRE",
      "name": "默认中丝割一刀",
      "conditions": {...},
      "output_params": {...},
      "priority": 5,
      "is_modified": false,
      "created_at": "2026-01-12T10:00:00"
    },
    ...
  ]
}
```

## 使用场景

### 场景1：价格库更新不影响已创建任务

```
1. 2026-01-01: 创建任务A，价格快照：慢丝 0.05元/mm²
2. 2026-01-15: 价格库更新，慢丝改为 0.06元/mm²
3. 任务A重算时，仍使用快照中的 0.05元/mm²
4. 新任务B创建时，使用新价格 0.06元/mm²
```

### 场景2：用户修改任务的价格

```
1. 任务A创建，价格快照：慢丝 0.05元/mm²
2. 用户觉得价格不合理，修改为 0.04元/mm²
3. 快照更新：unit_price=0.04, is_modified=true
4. 后续计算使用修改后的价格 0.04元/mm²
5. 原始价格库不受影响，仍为 0.05元/mm²
```

### 场景3：审计追溯

```
1. 查询任务A的价格快照
2. 查看is_modified字段，判断是否被修改
3. 查看modified_by字段，知道谁修改的
4. 查看original_price_id，追溯原始价格
5. 完整的审计链条
```

## ZQY使用快照

### DecisionAgent（工艺决策）

```python
# 不再查询process_rules表，而是查询快照表
async def get_process_rules(job_id: str):
    sql = """
        SELECT * FROM job_process_snapshots
        WHERE job_id = :job_id
          AND feature_type = 'WIRE'
        ORDER BY priority DESC
    """
    return await db.fetch_all(sql, {"job_id": job_id})
```

### PricingAgent（价格计算）

```python
# 不再查询price_items表，而是查询快照表
async def get_prices(job_id: str):
    sql = """
        SELECT * FROM job_price_snapshots
        WHERE job_id = :job_id
          AND feature_type = 'WIRE'
        ORDER BY priority DESC
    """
    return await db.fetch_all(sql, {"job_id": job_id})
```

## 优势

1. ✅ **数据一致性**：任务使用的价格和规则不会因为库更新而变化
2. ✅ **用户可控**：用户可以修改快照，不影响原始数据
3. ✅ **审计追溯**：完整记录价格和规则的使用和修改历史
4. ✅ **重算准确**：重算时使用相同的价格和规则
5. ✅ **版本管理**：支持价格和规则的版本管理

## 注意事项

1. **快照创建时机**：在jobs表插入后立即创建，确保在同一事务中
2. **快照数量**：每个任务会复制所有有效的价格和规则，数据量较大
3. **查询性能**：快照表需要建立索引（job_id, feature_type）
4. **修改权限**：只有任务所有者可以修改快照
5. **删除策略**：任务归档后，快照数据保留7年

## 总结

快照功能是系统的核心设计之一，确保了：
- ✅ 价格版本锁定
- ✅ 规则版本锁定
- ✅ 用户可修改
- ✅ 审计追溯
- ✅ 数据一致性

**状态**：✅ 已实现并集成到文件上传流程中
