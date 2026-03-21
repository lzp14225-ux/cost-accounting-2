# InteractionAgent V2 快速开始

## 1. 安装依赖

```bash
cd moldCost
pip install -r requirements.txt
```

主要依赖：
- `langchain>=1.0,<2.0`
- `langgraph>=1.0,<2.0`
- `langchain-openai>=0.1.0,<1.0`
- `openai>=1.0,<2.0`

## 2. 基础使用（3 分钟上手）

### 2.1 导入和初始化

```python
from agents.interaction_agent_wrapper import InteractionAgent

# 不使用 LLM（推荐生产环境）
agent = InteractionAgent(use_llm=False)

# 或使用 LLM 增强（需要 API Key）
# agent = InteractionAgent(use_llm=True)
```

### 2.2 检查参数

```python
context = {
    "job_id": "job-123",
    "features": [
        {
            "subgraph_id": "UP01",
            "volume_mm3": 1000,
            # thickness_mm 和 material 缺失
        }
    ]
}

result = await agent.process(context)

if result.status == "need_input":
    # 显示给用户
    print(result.data["prompt"])
    
    # 获取缺失参数列表
    for param in result.data["missing_params"]:
        print(f"{param['param_label']}: {param['param_type']}")
```

### 2.3 处理用户输入

```python
# 用户填写参数后
context["user_input"] = {
    "UP01": {
        "thickness_mm": 30,
        "material": "P20"
    }
}

result = await agent.process(context)

if result.status == "ok":
    print("✅ 参数完整，可以继续处理")
    updated_features = result.data["features"]
```

## 3. 完整示例

```python
import asyncio
from agents.interaction_agent_wrapper import InteractionAgent

async def main():
    agent = InteractionAgent(use_llm=False)
    
    # 初始上下文
    context = {
        "job_id": "demo-001",
        "features": [
            {
                "subgraph_id": "UP01",
                "volume_mm3": 1000,
            }
        ]
    }
    
    # 第一次检查
    result = await agent.process(context)
    
    if result.status == "need_input":
        print("缺失参数:")
        for param in result.data["missing_params"]:
            print(f"  • {param['param_label']}")
        
        # 模拟用户输入
        context["user_input"] = {
            "UP01": {
                "thickness_mm": 30,
                "material": "P20"
            }
        }
        
        # 第二次检查
        result = await agent.process(context)
    
    if result.status == "ok":
        print("✅ 完成!")

if __name__ == "__main__":
    asyncio.run(main())
```

## 4. 运行示例

```bash
# 运行完整示例
python examples/interaction_agent_example.py

# 运行测试
pytest tests/test_interaction_agent_v2.py -v
```

## 5. 与 Orchestrator 集成

```python
# 在 orchestrator_agent.py 中
from agents.interaction_agent_wrapper import InteractionAgent

class OrchestratorAgent:
    def __init__(self):
        self.interaction_agent = InteractionAgent(use_llm=False)
    
    async def execute(self, job_id: str, features: List[Dict]):
        # 检查参数
        context = {
            "job_id": job_id,
            "features": features
        }
        
        result = await self.interaction_agent.process(context)
        
        if result.status == "need_input":
            # 通过 WebSocket 推送给前端
            await self.push_to_frontend(
                job_id=job_id,
                missing_params=result.data["missing_params"],
                prompt=result.data["prompt"]
            )
            
            # 等待用户输入...
            return "waiting_for_input"
        
        # 参数完整，继续执行
        return await self.continue_processing(result.data["features"])
```

## 6. 配置 LLM（可选）

如果想使用 AI 生成更友好的提示：

```bash
# 设置环境变量
export OPENAI_API_KEY=sk-xxx

# 或在 .env 文件中
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o-mini  # 可选
```

```python
# 启用 LLM
agent = InteractionAgent(use_llm=True)
```

## 7. 常见问题

### Q1: 如何添加新的参数检查？

编辑 `interaction_agent_v2.py` 的 `_check_params` 方法：

```python
# 添加新的检查规则
if not feature.get("new_param"):
    missing.append({
        "subgraph_id": subgraph_id,
        "param_name": "new_param",
        "param_label": "新参数",
        "param_type": "text",
        "required": True
    })
```

### Q2: 如何自定义提示文本？

重写 `_generate_simple_prompt` 方法：

```python
def _generate_simple_prompt(self, missing):
    return "您的自定义提示文本"
```

### Q3: 性能如何？

- 不使用 LLM：< 10ms
- 使用 LLM：200-500ms（取决于 API 延迟）

建议生产环境禁用 LLM。

## 8. 下一步

- 阅读 [完整文档](INTERACTION_AGENT_V2.md)
- 查看 [API 参考](../docs/api_reference.md)
- 了解 [LangGraph 工作流](https://langchain-ai.github.io/langgraph/)

## 9. 获取帮助

- 查看示例代码：`examples/interaction_agent_example.py`
- 运行测试：`pytest tests/test_interaction_agent_v2.py -v`
- 联系负责人：人员B2
