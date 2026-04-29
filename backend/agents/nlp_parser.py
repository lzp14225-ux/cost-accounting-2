"""
NLP Parser - 自然语言解析器
负责人：人员B2

职责：
1. 解析用户的自然语言修改指令
2. 识别修改的表、记录ID、字段和值
3. 支持规则解析（快速）和 LLM 解析（智能）
4. 返回结构化的修改指令

架构：
- 规则解析：基于正则表达式，快速但有限
- LLM 解析：使用本地 Qwen，智能但较慢
- Fallback 机制：LLM 失败时降级到规则解析
"""
import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)


class NeedsConfirmationException(Exception):
    """
    需要用户确认的异常
    
    当智能匹配找到多个可能的目标时抛出此异常，
    要求用户从候选列表中选择一个。
    
    Attributes:
        message: 提示消息
        candidates: 候选列表
        original_input: 用户原始输入
        match_info: 匹配信息（用于调试）
    """
    
    def __init__(
        self,
        message: str,
        candidates: List[Dict[str, Any]],
        original_input: str,
        match_info: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.candidates = candidates
        self.original_input = original_input
        self.match_info = match_info or {}


class NLPParser:
    """
    自然语言解析器
    
    支持两种解析模式：
    1. 规则解析（rule-based）：快速，适合简单指令
    2. LLM 解析（llm-based）：智能，适合复杂指令
    """
    
    def __init__(self, use_llm: bool = True):
        """
        初始化 NLP Parser
        
        Args:
            use_llm: 是否使用 LLM（默认 True）
        """
        self.use_llm = use_llm
        
        # LLM 配置
        self.llm_base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
        self.llm_api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.llm_model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT") or settings.LLM_TIMEOUT)
        
        # HTTP 客户端（设置 User-Agent 以绕过 403 错误）
        self.http_client = httpx.AsyncClient(
            timeout=self.llm_timeout,
            headers={
                "User-Agent": "curl/8.0"
            }
        )
        
        logger.info(f"✅ NLPParser 初始化完成 (use_llm={use_llm}, timeout={self.llm_timeout}s)")
        if use_llm:
            logger.info(f"🤖 LLM: {self.llm_model} @ {self.llm_base_url}")
    
    async def parse(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        解析自然语言指令（集成智能匹配）
        
        Args:
            text: 用户输入的自然语言
            context: 当前数据上下文（可能包含 raw_data 和 display_view）
        
        Returns:
            解析后的修改列表，格式：
            [
                {
                    "table": "subgraphs",
                    "id": "UP01",
                    "field": "material",
                    "value": "718",
                    "original_text": "将 UP01 的材质改为 718"
                }
            ]
        
        Raises:
            NeedsConfirmationException: 当智能匹配找到多个候选时
        """
        logger.info(f"🔍 开始解析: {text}")
        
        try:
            # 🆕 检查是否有 display_view
            if "display_view" in context and context.get("display_view"):
                logger.info("🔧 使用展示视图解析")
                changes = await self._parse_with_display_view(text, context)
            else:
                logger.info("🔧 使用原始数据解析")
                changes = await self._parse_with_raw_data(text, context)
            
            # 🆕 智能匹配增强：如果解析结果为空或ID不明确，尝试智能匹配
            if not changes:
                logger.info("📋 解析结果为空，尝试智能匹配...")
                changes = await self._try_smart_matching(text, context)
            else:
                # 检查是否有不明确的ID（需要智能匹配）
                changes = await self._enhance_with_smart_matching(changes, context)
            
            return changes
        
        except NeedsConfirmationException:
            # 重新抛出确认异常
            raise
        except Exception as e:
            logger.error(f"❌ 解析失败: {e}", exc_info=True)
            return []
    
    async def _parse_with_raw_data(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        使用原始数据解析（原有逻辑）
        
        Args:
            text: 用户输入
            context: 原始数据上下文
        
        Returns:
            修改列表
        """
        # 获取 raw_data（向后兼容）
        raw_data = context.get("raw_data") or context
        
        try:
            # 优先使用 LLM 解析
            if self.use_llm:
                try:
                    # 🆕 将 user_input 和完整 context 传递
                    context_with_input = {**context, "user_input": text}
                    changes = await self._parse_with_llm(text, context_with_input)
                    if changes:
                        logger.info(f"✅ LLM 解析成功: {len(changes)} 个修改")
                        return changes
                    else:
                        logger.warning("⚠️  LLM 解析返回空结果，降级到规则解析")
                except NeedsConfirmationException:
                    # 🆕 重新抛出确认异常，不要降级
                    raise
                except Exception as e:
                    logger.error(f"❌ LLM 解析失败: {e}，降级到规则解析")
            
            # Fallback: 规则解析
            changes = await self._parse_with_rules(text, context)
            logger.info(f"✅ 规则解析完成: {len(changes)} 个修改")
            return changes
        
        except NeedsConfirmationException:
            # 🆕 重新抛出确认异常
            raise
        except Exception as e:
            logger.error(f"❌ 解析失败: {e}", exc_info=True)
            return []
    
    async def _parse_with_llm(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 解析自然语言
        
        Args:
            text: 用户输入
            context: 数据上下文
        
        Returns:
            解析后的修改列表
        """
        logger.info("🤖 使用 LLM 解析...")
        
        # 构建 Prompt
        prompt = self._build_prompt(text, context)
        
        # 调用 LLM API
        try:
            response = await self.http_client.post(
                f"{self.llm_base_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个数据修改指令解析助手。你的任务是将用户的自然语言指令解析为结构化的数据修改操作。"
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.1,  # 低温度，更确定性
                    "max_tokens": 2000  # 增加 token 限制，确保响应完整
                },
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            # 提取 LLM 响应
            content = result["choices"][0]["message"]["content"]
            logger.debug(f"🤖 LLM 完整响应: {content}")
            
            # 解析 JSON 响应
            changes = self._extract_json_from_llm_response(content)
            
            # 验证结果
            if changes:
                # 🆕 将用户输入添加到 context，用于自动修复
                context_with_input = {**context, "user_input": text}
                validated_changes = self._validate_changes(changes, context_with_input)
                return validated_changes
            else:
                logger.warning("⚠️  LLM 未返回有效的修改指令")
                return []
        
        except httpx.TimeoutException as e:
            logger.error(f"❌ LLM API 请求超时: {e}", exc_info=True)
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ LLM API 返回错误状态: {e.response.status_code} - {e.response.text}", exc_info=True)
            raise
        except httpx.HTTPError as e:
            logger.error(f"❌ LLM API 请求失败: {type(e).__name__} - {str(e)}", exc_info=True)
            raise
        except json.JSONDecodeError as e:
            logger.error(f"❌ LLM 响应 JSON 解析失败: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"❌ LLM 解析异常: {type(e).__name__} - {str(e)}", exc_info=True)
            raise
    
    def _build_prompt(self, text: str, context: Dict[str, Any]) -> str:
        """
        构建 LLM Prompt
        
        Args:
            text: 用户输入
            context: 数据上下文
        
        Returns:
            完整的 Prompt
        """
        # 提取数据结构信息
        tables_info = self._extract_tables_info(context)
        
        prompt = f"""请解析以下用户指令，并返回结构化的修改操作。

## 用户指令
{text}

## 当前数据结构
{tables_info}

## 输出格式
请以 JSON 数组格式返回，每个修改操作包含以下字段：
- table: 表名（features/price_snapshots/subgraphs）⚠️ 注意：不要使用 process_snapshots 表
- id: 记录ID（可以是 part_code、part_name 或实际的 ID，系统会自动映射）
- field: 要修改的字段名（必须是数据库中实际存在的字段）
- value: 新的值
- original_text: 原始指令文本

⚠️ 重要：
1. 必须返回有效的 JSON 格式
2. 字符串值中不要包含未转义的换行符、制表符等控制字符
3. 如果需要包含特殊字符，请使用 JSON 转义（如 \\n, \\t）
4. 确保 JSON 完整，不要截断

## 示例

### 示例1：修改材质（⚠️ 注意：material 字段在 features 表）
用户指令: "将 UP01 的材质改为 718"
输出:
```json
[
  {{
    "table": "features",
    "id": "UP01",
    "field": "material",
    "value": "718",
    "original_text": "将 UP01 的材质改为 718"
  }}
]
```

### 示例2：通过零件名称修改材质
用户指令: "请把上模板的材料换成 718"
输出:
```json
[
  {{
    "table": "features",
    "id": "上模板",
    "field": "material",
    "value": "718",
    "original_text": "请把上模板的材料换成 718"
  }}
]
```

### 示例2.5：批量修改某类零件的材质（⚠️ 重要：使用 filter）
用户指令: "下模板类的材料改成Cr12mov"
输出:
```json
[
  {{
    "table": "features",
    "filter": {{
      "part_name_contains": "下模板",
      "match_type": "contains"
    }},
    "field": "material",
    "value": "Cr12mov",
    "original_text": "下模板类的材料改成Cr12mov"
  }}
]
```

### 示例3：修改工艺信息
用户指令: "上夹板工艺改为快丝割一刀"
（⚠️ 注意：工艺修改应该修改 subgraphs 表的 wire_process 和 wire_process_note 字段）
输出:
```json
[
  {{
    "table": "subgraphs",
    "id": "上夹板",
    "field": "wire_process",
    "value": "fast_cut",
    "original_text": "上夹板工艺改为快丝割一刀"
  }},
  {{
    "table": "subgraphs",
    "id": "上夹板",
    "field": "wire_process_note",
    "value": "快丝割一刀",
    "original_text": "上夹板工艺改为快丝割一刀"
  }}
]
```

### 示例3.5：修改工艺为慢丝割一修三
用户指令: "上垫脚类工艺为慢丝割一修三"
（⚠️ 重要：慢丝割一修三的代码是 slow_and_three，不是 slow_cut_and_three！）
输出:
```json
[
  {{
    "table": "subgraphs",
    "id": "上垫脚类",
    "field": "wire_process",
    "value": "slow_and_three",
    "original_text": "上垫脚类工艺为慢丝割一修三"
  }},
  {{
    "table": "subgraphs",
    "id": "上垫脚类",
    "field": "wire_process_note",
    "value": "慢丝割一修三",
    "original_text": "上垫脚类工艺为慢丝割一修三"
  }}
]
```

### 示例4：批量修改特征
用户指令: "LP-02长度改为80，PH2-04宽度改为90"
输出:
```json
[
  {{
    "table": "features",
    "id": "LP-02",
    "field": "length_mm",
    "value": "80",
    "original_text": "LP-02长度改为80"
  }},
  {{
    "table": "features",
    "id": "PH2-04",
    "field": "width_mm",
    "value": "90",
    "original_text": "PH2-04宽度改为90"
  }}
]
```

### 示例5：全部修改（⚠️ 重要：使用特殊标识 "ALL"）
用户指令: "全部材质修改为45#"
输出:
```json
[
  {{
    "table": "features",
    "id": "ALL",
    "field": "material",
    "value": "45#",
    "original_text": "全部材质修改为45#"
  }}
]
```

### 示例6：全部工艺修改（⚠️ 特殊：工艺修改需要两个字段）
用户指令: "全部工艺改为快丝割一刀"
输出:
```json
[
  {{
    "table": "subgraphs",
    "id": "ALL",
    "field": "wire_process",
    "value": "fast_cut",
    "original_text": "全部工艺改为快丝割一刀"
  }},
  {{
    "table": "subgraphs",
    "id": "ALL",
    "field": "wire_process_note",
    "value": "快丝割一刀",
    "original_text": "全部工艺改为快丝割一刀"
  }}
]
```

### 示例7：批量修改价格（⚠️ 新增：基于过滤条件的批量修改）
用户指令: "将这套的线割割一修一的单价改成0.0018"
输出:
```json
[
  {{
    "table": "job_price_snapshots",
    "filter": {{
      "category": "wire",
      "sub_category": "slow_and_one"
    }},
    "field": "price",
    "value": "0.0018",
    "original_text": "将这套的线割割一修一的单价改成0.0018"
  }}
]
```

### 示例8：批量修改价格（通过工艺名称）
用户指令: "慢丝割一修一的价格改为0.002"
输出:
```json
[
  {{
    "table": "job_price_snapshots",
    "filter": {{
      "category": "wire",
      "sub_category": "slow_and_one",
      "note": "慢丝割一修一"
    }},
    "field": "price",
    "value": "0.002",
    "original_text": "慢丝割一修一的价格改为0.002"
  }}
]
```

### 示例9：批量修改材质价格（⚠️ 新增：材质价格修改）
用户指令: "45#价格改成6块"
输出:
```json
[
  {{
    "table": "job_price_snapshots",
    "filter": {{
      "category": "material",
      "sub_category": "45#"
    }},
    "field": "price",
    "value": "6",
    "original_text": "45#价格改成6块"
  }}
]
```

### 示例10：批量修改材质价格（完整表达）
用户指令: "将CR12的价格改为11.8"
输出:
```json
[
  {{
    "table": "job_price_snapshots",
    "filter": {{
      "category": "material",
      "sub_category": "CR12"
    }},
    "field": "price",
    "value": "11.8",
    "original_text": "将CR12的价格改为11.8"
  }}
]
```

### 示例11：通过材质筛选批量修改工艺（⚠️ 新增：material_equals 筛选）
用户指令: "将材质为Cr12mov的工艺改为慢丝割一修二"
输出:
```json
[
  {{
    "table": "subgraphs",
    "filter": {{
      "material_equals": "Cr12mov",
      "match_type": "material"
    }},
    "field": "wire_process",
    "value": "slow_and_two",
    "original_text": "将材质为Cr12mov的工艺改为慢丝割一修二"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "material_equals": "Cr12mov",
      "match_type": "material"
    }},
    "field": "wire_process_note",
    "value": "慢丝割一修二",
    "original_text": "将材质为Cr12mov的工艺改为慢丝割一修二"
  }}
]
```

### 示例12：通过尺寸筛选批量修改（⚠️ 新增：dimension_equals 筛选）
用户指令: "尺寸为200*150*30的零件材质改为718"
输出:
```json
[
  {{
    "table": "features",
    "filter": {{
      "dimension_equals": "200*150*30",
      "match_type": "dimension"
    }},
    "field": "material",
    "value": "718",
    "original_text": "尺寸为200*150*30的零件材质改为718"
  }}
]
```

## 🆕 特殊场景：多关键词批量修改

### 场景识别
当用户说"冲头刀口入块都改成..."时，表示要批量修改多类零件：
- 零件关键词: 多个，可能连写（无分隔符）
- 匹配方式: 包含匹配（part_name 包含关键词即可）
- 批量操作: 每个关键词对应一组零件

### 分词规则
1. 优先识别常见零件名称（2-4字）：
   - 冲头、刀口、入块、模板、夹板、垫板、导柱、导套、顶针等
2. 如果有分隔符（逗号、顿号、"和"字），按分隔符分词
3. 如果无分隔符，使用零件名称常识进行智能分词

### 输出格式（多关键词场景）
```json
[
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "冲头",
      "match_type": "contains"
    }},
    "field": "wire_process",
    "value": "slow_and_one",
    "original_text": "冲头刀口入块都改成慢丝割一修一"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "冲头",
      "match_type": "contains"
    }},
    "field": "wire_process_note",
    "value": "慢丝割一修一",
    "original_text": "冲头刀口入块都改成慢丝割一修一"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "刀口",
      "match_type": "contains"
    }},
    "field": "wire_process",
    "value": "slow_and_one",
    "original_text": "冲头刀口入块都改成慢丝割一修一"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "刀口",
      "match_type": "contains"
    }},
    "field": "wire_process_note",
    "value": "慢丝割一修一",
    "original_text": "冲头刀口入块都改成慢丝割一修一"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "入块",
      "match_type": "contains"
    }},
    "field": "wire_process",
    "value": "slow_and_one",
    "original_text": "冲头刀口入块都改成慢丝割一修一"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "入块",
      "match_type": "contains"
    }},
    "field": "wire_process_note",
    "value": "慢丝割一修一",
    "original_text": "冲头刀口入块都改成慢丝割一修一"
  }}
]
```

### 示例

**输入1**: "冲头刀口入块都改成慢丝割一修一"
**分词**: ["冲头", "刀口", "入块"]
**输出**: 6个修改操作（3个关键词 × 2个字段）

**输入2**: "上模板下模板都改成快丝割一刀"
**分词**: ["上模板", "下模板"]
**输出**: 4个修改操作（2个关键词 × 2个字段）

**输入3**: "冲头、刀口都改成慢丝割一修一"
**分词**: ["冲头", "刀口"]（按逗号分隔）
**输出**: 4个修改操作

### 注意事项
1. 每个关键词生成一个独立的修改操作（带 filter）
2. 同时修改 wire_process 和 wire_process_note 两个字段
3. 如果无法确定分词边界，在 reasoning 中说明

### 🆕 概念词支持
系统支持以下概念词，会自动展开为多个关键词进行模糊匹配：
- **冲头**: 会匹配所有包含"切边冲头"、"切冲冲头"、"冲子"、"废料刀"、"冲头"的零件
- **刀口入块**: 会匹配所有包含"刀口入子"、"切边入子"、"冲孔入子"、"凹模"的零件
- **模架**: 会匹配所有包含"模座"、"垫脚"、"托板"的零件

**重要**: 如果用户使用概念词（如"冲头都改成..."），你只需要返回概念词本身，系统会自动展开：

**输入**: "冲头都改成慢丝割一修一"
**输出**: 
```json
[
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "冲头",
      "match_type": "contains"
    }},
    "field": "wire_process",
    "value": "slow_and_one",
    "original_text": "冲头都改成慢丝割一修一"
  }},
  {{
    "table": "subgraphs",
    "filter": {{
      "part_name_contains": "冲头",
      "match_type": "contains"
    }},
    "field": "wire_process_note",
    "value": "慢丝割一修一",
    "original_text": "冲头都改成慢丝割一修一"
  }}
]
```

系统会自动将"冲头"展开为["切边冲头", "切冲冲头", "冲子", "废料刀", "冲头"]并匹配所有相关零件。

## 重要规则
1. **ID 可以灵活使用**: 可以使用 part_code（如 LP-02）、part_name（如"上夹板"）、实际的 ID（如 UP01），或特殊标识 "ALL"（表示全部记录），系统会自动映射
2. **字段名映射**:
   - 材质/材料 → material (⚠️ features 表)
   - 长度 → length_mm (features 表)
   - 宽度 → width_mm (features 表)
   - 厚度 → thickness_mm (features 表)
   - 数量 → quantity (features 表)
   - 工艺代码 → wire_process (subgraphs 表)
   - 工艺说明 → wire_process_note (subgraphs 表)
   - 价格/单价 → price (job_price_snapshots 表)
3. **表名判断（重要！）**:
   - 修改材质、尺寸（长宽厚）、数量 → features 表
   - 修改工艺、加工方式 → subgraphs 表 (wire_process, wire_process_note)
   - 修改价格、成本 → job_price_snapshots 表
   - 修改零件名称、零件编码 → subgraphs 表
4. **支持批量修改**: 如果用户一次修改多个字段或多个记录，返回多个修改操作
5. **全部修改**: 如果用户说"全部"、"所有"等，使用 id="ALL"，系统会自动展开为所有记录
6. **🆕 过滤条件修改**: 如果用户说"将这套的线割割一修一的单价改成X"或"45#价格改成X"，使用 filter 字段：
   - **线割工艺**（⚠️ 重要：必须使用以下精确的代码，不要自己创造）:
     * "线割割一修三" → filter: {{"category": "wire", "sub_category": "slow_and_three"}}
     * "线割割一修二" → filter: {{"category": "wire", "sub_category": "slow_and_two"}}
     * "线割割一修一" → filter: {{"category": "wire", "sub_category": "slow_and_one"}}
     * "线割割一刀" → filter: {{"category": "wire", "sub_category": "slow_cut"}}
     * "慢丝割一修三" → sub_category="slow_and_three" (不是 slow_cut_and_three!)
     * "慢丝割一修二" → sub_category="slow_and_two"
     * "慢丝割一修一" → sub_category="slow_and_one"
     * "慢丝割一刀" → sub_category="slow_cut"
     * "中丝割一修一" → sub_category="middle_and_one"
     * "快丝割一刀" → sub_category="fast_cut"
   - **材质**:
     * "45#" → filter: {{"category": "material", "sub_category": "45#"}}
     * "CR12" → filter: {{"category": "material", "sub_category": "CR12"}}
     * "SKD11" → filter: {{"category": "material", "sub_category": "SKD11"}}
     * "CR12MOV" → filter: {{"category": "material", "sub_category": "CR12MOV"}}
     * "SKH-51" → filter: {{"category": "material", "sub_category": "SKH-51"}}
     * "SKH-9" → filter: {{"category": "material", "sub_category": "SKH-9"}}
     * "T00L0X33" 或 "TOOLOX33" → filter: {{"category": "material", "sub_category": "T00L0X33"}}
     * "T00L0X44" 或 "TOOLOX44" → filter: {{"category": "material", "sub_category": "T00L0X44"}}
     * "P20" → filter: {{"category": "material", "sub_category": "P20"}}
     * "DC53" → filter: {{"category": "material", "sub_category": "DC53"}}
7. **只返回 JSON**: 不要有其他解释文字
8. **如果无法解析**: 返回空数组 []
9. **⚠️ 重要**: 不要使用 process_snapshots 表，工艺信息存储在 subgraphs 表中

请开始解析："""
        
        return prompt
    
    def _extract_tables_info(self, context: Dict[str, Any]) -> str:
        """
        提取数据表信息（用于 Prompt）
        
        Args:
            context: 数据上下文
        
        Returns:
            表信息的文本描述
        """
        info_lines = []
        
        # Features 表
        if context.get("features"):
            features = context["features"]
            info_lines.append(f"### features 表 ({len(features)} 条记录)")
            if features:
                sample = features[0]
                fields = list(sample.keys())
                info_lines.append(f"字段: {', '.join(fields[:10])}")  # 只显示前10个字段
                info_lines.append(f"示例 ID: {sample.get('feature_id', 'N/A')}")
        
        # Subgraphs 表（重点）
        if context.get("subgraphs"):
            subgraphs = context["subgraphs"]
            info_lines.append(f"\n### subgraphs 表 ({len(subgraphs)} 条记录)")
            if subgraphs:
                sample = subgraphs[0]
                fields = list(sample.keys())
                info_lines.append(f"字段: {', '.join(fields[:10])}")
                
                # 列出所有记录的 ID 和名称映射（重要！）
                info_lines.append("\n**ID 和名称映射**:")
                for s in subgraphs:
                    sg_id = s.get('subgraph_id', 'N/A')
                    part_name = s.get('part_name', 'N/A')
                    info_lines.append(f"  - {sg_id}: {part_name}")
        
        # Price Snapshots 表
        if context.get("job_price_snapshots"):
            snapshots = context["job_price_snapshots"]
            info_lines.append(f"\n### job_price_snapshots 表 ({len(snapshots)} 条记录)")
            if snapshots:
                sample = snapshots[0]
                fields = list(sample.keys())
                info_lines.append(f"字段: {', '.join(fields[:10])}")
        
        # ⚠️ 不再显示 process_snapshots 表（已移除）
        
        return "\n".join(info_lines) if info_lines else "（当前无数据）"
    
    def _extract_json_from_llm_response(self, content: str) -> List[Dict[str, Any]]:
        """
        从 LLM 响应中提取 JSON
        
        Args:
            content: LLM 响应内容
        
        Returns:
            解析后的 JSON 列表
        """
        # 🆕 预处理：移除或转义无效的控制字符
        def clean_json_string(s: str) -> str:
            """清理 JSON 字符串中的无效控制字符"""
            # 移除常见的控制字符（保留 \n, \r, \t）
            import string
            # 允许的控制字符：换行、回车、制表符
            allowed_controls = {'\n', '\r', '\t'}
            cleaned = ''.join(
                char if char not in string.whitespace or char in allowed_controls or ord(char) >= 32
                else ' '
                for char in s
            )
            return cleaned
        
        # 清理输入
        content = clean_json_string(content)
        
        try:
            # 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取 JSON 代码块
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(1).strip()
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️  JSON 代码块解析失败: {e}")
                logger.debug(f"📋 提取的 JSON 字符串: {json_str[:500]}")
        
        # 尝试提取数组（更宽松的匹配）
        array_match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
        if array_match:
            try:
                json_str = array_match.group(0)
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️  数组解析失败: {e}")
                logger.debug(f"📋 提取的数组字符串: {json_str[:500]}")
        
        # 🆕 尝试修复常见的 JSON 错误
        # 1. 移除 ```json 标记
        cleaned = re.sub(r'```json\s*', '', content)
        cleaned = re.sub(r'\s*```', '', cleaned)
        
        # 2. 尝试找到第一个 [ 和最后一个 ]
        start_idx = cleaned.find('[')
        end_idx = cleaned.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                json_str = cleaned[start_idx:end_idx+1]
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️  修复后的 JSON 解析失败: {e}")
                logger.debug(f"📋 修复后的 JSON: {json_str[:500]}")
                
                # 🆕 尝试使用 strict=False（允许控制字符）
                try:
                    return json.loads(json_str, strict=False)
                except json.JSONDecodeError as e2:
                    logger.warning(f"⚠️  宽松模式解析也失败: {e2}")
        
        logger.warning(f"⚠️  无法从 LLM 响应中提取 JSON")
        logger.debug(f"📋 完整响应内容: {content}")
        return []
    
    def _validate_changes(
        self,
        changes: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        验证修改指令的有效性
        
        Args:
            changes: 待验证的修改列表
            context: 数据上下文
        
        Returns:
            验证后的修改列表
        """
        validated = []
        
        for change in changes:
            # 检查必需字段
            if not all(k in change for k in ["table", "field", "value"]):
                logger.warning(f"⚠️  修改指令缺少必需字段: {change}")
                continue
            
            # 🆕 智能修复：如果缺少 id 和 filter，尝试从 original_text 提取
            if "id" not in change and "filter" not in change:
                logger.warning(f"⚠️  修改指令缺少 id 或 filter，尝试自动修复: {change}")
                
                # 尝试从 original_text 提取材质或工艺信息
                original_text = change.get("original_text", "")
                
                # 🆕 如果 change 中没有 original_text，尝试从 context 获取
                if not original_text and "user_input" in context:
                    original_text = context.get("user_input", "")
                    logger.info(f"📝 使用 context 中的 user_input: {original_text}")
                
                if original_text:
                    from shared.process_code_mapping import extract_process_from_text
                    
                    process_code = extract_process_from_text(original_text)
                    if process_code:
                        # 找到了材质或工艺代码，添加 filter
                        change["filter"] = {
                            "category": process_code.get("category"),
                            "sub_category": process_code.get("sub_category")
                        }
                        # 同时添加 original_text
                        if "original_text" not in change:
                            change["original_text"] = original_text
                        logger.info(f"✅ 自动添加 filter: {change['filter']}")
                    else:
                        logger.warning(f"⚠️  无法自动修复，跳过此修改")
                        continue
                else:
                    logger.warning(f"⚠️  无 original_text，无法自动修复，跳过此修改")
                    continue
            
            # 🆕 智能字段映射：自动修正错误的表名
            change = self._auto_correct_table_mapping(change)
            
            # 检查表名
            if change["table"] not in ["features", "job_price_snapshots", "subgraphs"]:
                logger.warning(f"⚠️  无效的表名: {change['table']}, 只支持 features/job_price_snapshots/subgraphs")
                continue
            
            # 🆕 处理工艺代码映射（针对 filter 中的中文工艺名称）
            if "filter" in change:
                change = self._resolve_process_filter(change)

            # 🆕 线割工艺默认值：用户只说“慢丝/中丝/快丝”时补成完整工艺
            change = self._normalize_wire_process_change(change)
            
            # 🆕 处理包含匹配过滤器
            if "filter" in change and "part_name_contains" in change["filter"]:
                logger.info(f"🔍 检测到包含匹配过滤器: {change['filter']}")
                
                # 应用包含匹配，展开为具体的修改操作
                expanded_changes = self._apply_contains_filter(change, context)
                
                if expanded_changes:
                    validated.extend(expanded_changes)
                    logger.info(f"✅ 包含匹配展开: {len(expanded_changes)} 个修改操作")
                else:
                    logger.warning(f"⚠️  包含匹配未找到任何零件")
                
                continue  # 已处理，跳过后续逻辑
            
            # 🆕 处理材质筛选过滤器
            if "filter" in change and "material_equals" in change["filter"]:
                logger.info(f"🔍 检测到材质筛选过滤器: {change['filter']}")
                
                # 应用材质筛选，展开为具体的修改操作
                expanded_changes = self._apply_material_filter(change, context)
                
                if expanded_changes:
                    validated.extend(expanded_changes)
                    logger.info(f"✅ 材质筛选展开: {len(expanded_changes)} 个修改操作")
                else:
                    logger.warning(f"⚠️  材质筛选未找到任何零件")
                
                continue  # 已处理，跳过后续逻辑
            
            # 🆕 处理尺寸筛选过滤器
            if "filter" in change and "dimension_equals" in change["filter"]:
                logger.info(f"🔍 检测到尺寸筛选过滤器: {change['filter']}")
                
                # 应用尺寸筛选，展开为具体的修改操作
                expanded_changes = self._apply_dimension_filter(change, context)
                
                if expanded_changes:
                    validated.extend(expanded_changes)
                    logger.info(f"✅ 尺寸筛选展开: {len(expanded_changes)} 个修改操作")
                else:
                    logger.warning(f"⚠️  尺寸筛选未找到任何零件")
                
                continue  # 已处理，跳过后续逻辑
            
            # 🆕 处理 "ALL" 标识：展开为所有记录
            if change.get("id") == "ALL":
                expanded_changes = self._expand_all_modification(change, context)
                validated.extend(expanded_changes)
                continue
            
            # 🆕 ID 映射：如果 ID 看起来像 part_code，尝试映射到实际的 ID
            # 🔑 支持多个匹配：如果有多个相同的零件编号，展开为多个修改
            if "id" in change:
                matched_ids = self._map_identifier_to_ids(
                    change["id"],
                    change["table"],
                    context
                )
                
                if len(matched_ids) == 0:
                    # 没有找到匹配，使用原始标识符
                    logger.warning(f"⚠️  未找到 {change['id']} 的映射，使用原始值")
                    validated.append(change)
                elif len(matched_ids) == 1:
                    # 只有一个匹配，直接使用
                    change["id"] = matched_ids[0]
                    validated.append(change)
                else:
                    # 🆕 多个匹配，需要用户确认
                    logger.info(f"🔍 找到 {len(matched_ids)} 个相同的 {change['id']}，需要用户确认")
                    
                    # 构建候选列表
                    candidates = self._build_candidates_from_ids(
                        matched_ids,
                        change["table"],
                        context
                    )
                    
                    # 抛出确认异常
                    raise NeedsConfirmationException(
                        message=f"找到 {len(matched_ids)} 个编号为 {change['id']} 的零件，请选择要修改的零件：",
                        candidates=candidates,
                        original_input=change.get("original_text", ""),
                        match_info={
                            "match_type": "duplicate_part_code",
                            "part_code": change["id"],
                            "count": len(matched_ids),
                            "pending_change": change  # 保存待执行的修改
                        }
                    )
            
            # 添加原始文本（如果缺失）
            if "original_text" not in change:
                if "id" in change:
                    change["original_text"] = f"修改 {change['table']}.{change['id']}.{change['field']} = {change['value']}"
                else:
                    change["original_text"] = f"批量修改 {change['table']}.{change['field']} = {change['value']}"
            
            validated.append(change)
        
        # 🆕 去重：如果同一个 table + id + field 被多个关键词匹配到，只保留一次
        seen = set()
        deduplicated = []
        
        for change in validated:
            key = (change["table"], change.get("id"), change["field"])
            if key not in seen:
                seen.add(key)
                deduplicated.append(change)
            else:
                logger.debug(f"⏭️  跳过重复修改: {change['table']}.{change.get('id')}.{change['field']}")
        
        if len(deduplicated) < len(validated):
            logger.info(f"✅ 去重后: {len(deduplicated)} 个修改操作（原 {len(validated)} 个）")
        
        return deduplicated
    
    def _expand_all_modification(
        self,
        change: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        展开 "ALL" 修改为所有记录
        
        Args:
            change: 包含 id="ALL" 的修改指令
            context: 数据上下文
        
        Returns:
            展开后的修改列表
        """
        table = change["table"]
        field = change["field"]
        value = change["value"]
        original_text = change.get("original_text", "")
        
        expanded = []
        raw_data = context.get("raw_data") or context
        
        if table == "features":
            # 修改所有 features 记录
            features = raw_data.get("features", [])
            for feature in features:
                feature_id = feature.get("feature_id")
                if feature_id:
                    expanded.append({
                        "table": "features",
                        "id": feature_id,
                        "field": field,
                        "value": value,
                        "original_text": original_text
                    })
            logger.info(f"✅ 展开 ALL 修改: features 表 {len(expanded)} 条记录")
        
        elif table == "subgraphs":
            # 修改所有 subgraphs 记录
            subgraphs = raw_data.get("subgraphs", [])
            for subgraph in subgraphs:
                subgraph_id = subgraph.get("subgraph_id")
                if subgraph_id:
                    expanded.append({
                        "table": "subgraphs",
                        "id": subgraph_id,
                        "field": field,
                        "value": value,
                        "original_text": original_text
                    })
            logger.info(f"✅ 展开 ALL 修改: subgraphs 表 {len(expanded)} 条记录")
        
        elif table == "job_price_snapshots":
            # 修改所有 job_price_snapshots 记录
            price_snapshots = raw_data.get("job_price_snapshots", [])
            for snapshot in price_snapshots:
                snapshot_id = snapshot.get("snapshot_id")
                if snapshot_id:
                    expanded.append({
                        "table": "job_price_snapshots",
                        "id": snapshot_id,
                        "field": field,
                        "value": value,
                        "original_text": original_text
                    })
            logger.info(f"✅ 展开 ALL 修改: job_price_snapshots 表 {len(expanded)} 条记录")
        
        return expanded
    
    def _resolve_process_filter(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析过滤条件中的工艺代码
        
        Args:
            change: 修改指令
        
        Returns:
            解析后的修改指令
        """
        from shared.process_code_mapping import extract_process_from_text
        
        filter_conditions = change.get("filter", {})
        
        # 如果 filter 中有 process_name 字段，尝试解析
        if "process_name" in filter_conditions:
            process_name = filter_conditions.pop("process_name")
            process_code = extract_process_from_text(process_name)
            
            if process_code:
                # 合并工艺代码到 filter
                filter_conditions.update(process_code)
                logger.info(f"✅ 工艺代码解析: {process_name} → {process_code}")
            else:
                logger.warning(f"⚠️  无法解析工艺代码: {process_name}")
        
        # 检查 original_text 中是否包含工艺名称
        original_text = change.get("original_text", "")
        if original_text and not filter_conditions:
            process_code = extract_process_from_text(original_text)
            if process_code:
                filter_conditions.update(process_code)
                logger.info(f"✅ 从原始文本解析工艺代码: {original_text} → {process_code}")
        
        change["filter"] = filter_conditions
        return change
    
    def _auto_correct_table_mapping(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """
        自动修正字段到表的映射
        
        Args:
            change: 修改指令
        
        Returns:
            修正后的修改指令
        """
        field = change.get("field")
        table = change.get("table")
        
        # 定义字段到表的正确映射
        field_to_table = {
            # Features 表字段
            "material": "features",
            "length_mm": "features",
            "width_mm": "features",
            "thickness_mm": "features",
            "quantity": "features",
            "heat_treatment": "features",
            "calculated_weight_kg": "features",
            
            # Subgraphs 表字段
            "wire_process": "subgraphs",
            "wire_process_note": "subgraphs",
            "part_name": "subgraphs",
            "part_code": "subgraphs",
            "weight_kg": "subgraphs",
            "total_cost": "subgraphs",
            
            # Price Snapshots 表字段
            "price": "job_price_snapshots",
            "unit_price": "job_price_snapshots"
        }
        
        correct_table = field_to_table.get(field)
        
        if correct_table and correct_table != table:
            logger.warning(f"⚠️  字段 {field} 应该在 {correct_table} 表，而不是 {table} 表，已自动修正")
            change["table"] = correct_table
        
        return change
    
    def _map_identifier_to_id(
        self,
        identifier: str,
        table: str,
        context: Dict[str, Any]
    ) -> str:
        """
        将标识符映射到实际的 ID（单个）
        
        ⚠️ 注意：如果有多个匹配，只返回第一个
        如果需要返回所有匹配，请使用 _map_identifier_to_ids
        
        Args:
            identifier: 标识符（可能是 part_code、subgraph_id 或其他）
            table: 表名
            context: 数据上下文
        
        Returns:
            实际的 ID
        """
        ids = self._map_identifier_to_ids(identifier, table, context)
        if ids:
            if len(ids) > 1:
                logger.warning(f"⚠️  找到 {len(ids)} 个匹配的 {identifier}，只返回第一个")
            return ids[0]
        
        # 如果没有找到映射，返回原始标识符
        logger.warning(f"⚠️  未找到 {identifier} 的映射，使用原始值")
        return identifier
    
    def _map_identifier_to_ids(
        self,
        identifier: str,
        table: str,
        context: Dict[str, Any]
    ) -> List[str]:
        """
        将标识符映射到实际的 ID 列表（支持多个匹配）
        
        Args:
            identifier: 标识符（可能是 part_code、subgraph_id 或其他）
            table: 表名
            context: 数据上下文
        
        Returns:
            实际的 ID 列表
        """
        # 如果标识符包含下划线且看起来像 job_id_part_code 格式，提取 part_code
        if "_" in identifier and len(identifier) > 36:  # UUID 长度是 36
            # 可能是 "job_id_part_code" 格式，提取最后一部分
            parts = identifier.split("_")
            if len(parts) >= 2:
                potential_part_code = "_".join(parts[-1:])  # 取最后一部分
                logger.info(f"🔍 检测到复合 ID，提取 part_code: {potential_part_code}")
                identifier = potential_part_code
        
        # 获取原始数据
        raw_data = context.get("raw_data") or context
        matched_ids = []
        
        # 🆕 如果使用 display_view，需要从 display_view 构建 subgraphs 映射
        if "display_view" in context and not raw_data.get("subgraphs"):
            display_view = context.get("display_view", [])
            # 从 display_view 构建临时的 subgraphs 列表（用于映射）
            temp_subgraphs = []
            for item in display_view:
                # ✅ 修复：part_code 和 part_name 在顶层，不在 _source 中
                source = item.get("_source", {})
                temp_subgraphs.append({
                    "subgraph_id": source.get("subgraph_id"),
                    "part_code": item.get("part_code"),  # ✅ 从顶层获取
                    "part_name": item.get("part_name", "")  # ✅ 从顶层获取
                })
            raw_data = {"subgraphs": temp_subgraphs, **raw_data}
            logger.info(f"✅ 从 display_view 构建了 {len(temp_subgraphs)} 个 subgraph 映射")
            
            # 🆕 调试：打印前5个 part_code
            part_codes = [sg.get("part_code") for sg in temp_subgraphs[:5]]
            logger.info(f"🔍 前5个 part_code: {part_codes}")
            logger.info(f"🔍 正在查找: {identifier}")
        
        # 根据表名进行映射
        if table == "features":
            # 尝试通过 subgraph_id 或 part_code 查找 feature_id
            features = raw_data.get("features", [])
            subgraphs = raw_data.get("subgraphs", [])
            
            # 先尝试直接匹配 feature_id
            for feature in features:
                if feature.get("feature_id") == identifier:
                    matched_ids.append(identifier)
            
            if matched_ids:
                return matched_ids
            
            # 尝试通过 part_code 查找（可能有多个）
            for subgraph in subgraphs:
                if subgraph.get("part_code") == identifier or subgraph.get("part_name") == identifier:
                    subgraph_id = subgraph.get("subgraph_id")
                    # 查找对应的 feature
                    for feature in features:
                        if feature.get("subgraph_id") == subgraph_id:
                            feature_id = feature.get("feature_id")
                            if feature_id not in matched_ids:
                                matched_ids.append(feature_id)
                                logger.info(f"✅ 映射 {identifier} → {feature_id}")
            
            if matched_ids:
                return matched_ids
            
            # 尝试通过 subgraph_id 查找
            for feature in features:
                if feature.get("subgraph_id") == identifier:
                    feature_id = feature.get("feature_id")
                    if feature_id not in matched_ids:
                        matched_ids.append(feature_id)
                        logger.info(f"✅ 通过 subgraph_id 找到 feature: {feature_id}")
        
        elif table == "subgraphs":
            # 尝试通过 part_code 查找 subgraph_id（可能有多个）
            subgraphs = raw_data.get("subgraphs", [])
            
            # 先尝试直接匹配 subgraph_id
            for subgraph in subgraphs:
                if subgraph.get("subgraph_id") == identifier:
                    matched_ids.append(identifier)
            
            if matched_ids:
                return matched_ids
            
            # 🆕 尝试通过 part_code 查找（支持模糊匹配）
            from shared.input_normalizer import InputNormalizer
            normalizer = InputNormalizer()
            
            # 生成标识符的所有变体（大小写、连字符等）
            identifier_variants = normalizer.normalize_subgraph_id(identifier)
            
            for subgraph in subgraphs:
                part_code = subgraph.get("part_code", "")
                part_name = subgraph.get("part_name", "")
                
                # 🆕 跳过 part_code 为 None 或空的记录
                if not part_code:
                    continue
                
                # 精确匹配
                if part_code == identifier or part_name == identifier:
                    subgraph_id = subgraph.get("subgraph_id")
                    # 🆕 确保 subgraph_id 不是 None
                    if subgraph_id and subgraph_id not in matched_ids:
                        matched_ids.append(subgraph_id)
                        logger.info(f"✅ 映射 {identifier} → {subgraph_id} (精确匹配)")
                    elif not subgraph_id:
                        logger.warning(f"⚠️  找到匹配的 part_code={part_code}，但 subgraph_id 为 None")
                    continue
                
                # 🆕 模糊匹配：检查 part_code 是否匹配任何变体
                part_code_upper = part_code.upper()
                for variant in identifier_variants:
                    if part_code_upper == variant.upper():
                        subgraph_id = subgraph.get("subgraph_id")
                        # 🆕 确保 subgraph_id 不是 None
                        if subgraph_id and subgraph_id not in matched_ids:
                            matched_ids.append(subgraph_id)
                            logger.info(f"✅ 映射 {identifier} → {subgraph_id} (模糊匹配: {variant})")
                        elif not subgraph_id:
                            logger.warning(f"⚠️  找到匹配的 part_code={part_code} (模糊)，但 subgraph_id 为 None")
                        break
        
        # ⚠️ 不再支持 process_snapshots 表
        
        elif table == "job_price_snapshots":
            # 尝试通过 part_code 或其他标识符查找 snapshot_id
            price_snapshots = raw_data.get("job_price_snapshots", [])
            
            # 先尝试直接匹配 snapshot_id
            for price in price_snapshots:
                if price.get("snapshot_id") == identifier:
                    matched_ids.append(identifier)
            
            # 可以根据需要添加更多映射逻辑
        
        return matched_ids
    
    async def _parse_with_rules(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        解析自然语言
        
        🆕 策略：直接使用 LLM 解析（LLM 优先策略）
        
        原实现：使用4个正则模式匹配固定句式
        - 模式1: "将 X 的 Y 改为 Z"
        - 模式2: "修改 X 的 Y 为 Z"
        - 模式3: "把 X 的 Y 设置为 Z"
        - 模式4: "X 的 Y 改成 Z"
        
        问题：
        - ❌ 只支持4种固定句式
        - ❌ 用户可能使用其他表达方式（"换成"、"调整为"、"更新为"...）
        - ❌ 正则容易误匹配
        
        新策略：直接使用 LLM
        - ✅ 支持所有表达方式
        - ✅ 不需要维护正则模式
        - ✅ 代码简单（~5行 vs ~100行）
        
        Args:
            text: 用户输入
            context: 数据上下文
        
        Returns:
            解析后的修改列表
        """
        logger.info("🤖 使用 LLM 解析（LLM 优先策略：准确性 > 性能）")
        
        try:
            # 直接使用 LLM 解析
            context_with_input = {**context, "user_input": text}
            return await self._parse_with_llm(text, context_with_input)
        except Exception as e:
            logger.error(f"❌ LLM 解析失败: {e}", exc_info=True)
            return []
    
    def _infer_table(
        self,
        record_id: str,
        field: str,
        context: Dict[str, Any]
    ) -> str:
        """
        推断记录所属的表
        
        Args:
            record_id: 记录ID
            field: 字段名
            context: 数据上下文
        
        Returns:
            表名
        """
        # 检查 subgraphs（最常见）
        if context.get("subgraphs"):
            for subgraph in context["subgraphs"]:
                if subgraph.get("subgraph_id") == record_id:
                    return "subgraphs"
        
        # 检查 features
        if context.get("features"):
            for feature in context["features"]:
                if str(feature.get("feature_id")) == record_id:
                    return "features"
        
        # 检查 job_price_snapshots
        if context.get("job_price_snapshots"):
            for snapshot in context["job_price_snapshots"]:
                if str(snapshot.get("snapshot_id")) == record_id:
                    return "job_price_snapshots"
        
        # ⚠️ 不再检查 process_snapshots（已移除）
        
        # 默认返回 subgraphs（最常用）
        logger.warning(f"⚠️  无法推断 {record_id} 的表，默认使用 subgraphs")
        return "subgraphs"
    
    def _normalize_field_name(self, field: str) -> str:
        """
        标准化字段名（中文 -> 英文）
        
        Args:
            field: 中文字段名
        
        Returns:
            英文字段名
        """
        field_mapping = {
            # Subgraphs 常用字段
            "材质": "material",
            "材料": "material",
            "重量": "weight_kg",
            "总成本": "total_cost",
            "成本": "total_cost",
            "工艺说明": "process_description",
            "说明": "process_description",
            
            # Features 常用字段
            "长度": "length_mm",
            "宽度": "width_mm",
            "厚度": "thickness_mm",
            "数量": "quantity",
            "热处理": "heat_treatment",
            
            # Price Snapshots 常用字段
            "价格": "price",
            "单价": "unit_price",
            "单位": "unit",
            
            # Process Snapshots 常用字段
            "名称": "name",
            "描述": "description",
            "优先级": "priority"
        }
        
        return field_mapping.get(field, field)
    
    async def _parse_with_display_view(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        使用展示视图解析（支持 part_code）
        
        Args:
            text: 用户输入
            context: 包含 raw_data 和 display_view 的上下文
        
        Returns:
            存储层修改列表
        """
        from agents.data_view_builder import DataViewBuilder
        
        logger.info("🔧 使用展示视图解析...")
        
        # 🆕 检测是否为工艺修改（包含"工艺"关键词）
        is_process_modification = any(keyword in text for keyword in ['工艺', 'process', '快丝', '慢丝', '割'])
        
        if is_process_modification:
            logger.info("🔍 检测到工艺修改，使用特殊处理...")
            return await self._parse_process_modification(text, context)
        
        # 🆕 检测是否为批量修改（包含逗号、顿号或"和"）
        is_batch = any(sep in text for sep in ['，', ',', '、', '和'])
        
        if is_batch:
            # 批量修改：直接使用 LLM 解析
            logger.info("🔍 检测到批量修改，使用 LLM 解析...")
            
            if self.use_llm:
                try:
                    # 🆕 将 user_input 和 display_view 添加到 context
                    context_with_input = {
                        **context,  # 保留完整的 context（包括 display_view）
                        "user_input": text
                    }
                    changes = await self._parse_with_llm(text, context_with_input)
                    if changes:
                        logger.info(f"✅ LLM 解析成功: {len(changes)} 个修改")
                        return changes
                except httpx.TimeoutException as e:
                    logger.error(f"❌ LLM 解析超时（{self.llm_timeout}秒）: {str(e)}", exc_info=True)
                except Exception as e:
                    logger.error(f"❌ LLM 解析失败: {type(e).__name__} - {str(e)}", exc_info=True)
            
            # 回退到规则解析
            logger.warning("⚠️  回退到规则解析")
            return await self._parse_with_rules(text, context)
        
        # 单个修改：尝试快速实体提取
        entities = await self._extract_entities_from_text(text)
        
        if entities:
            display_view = context.get("display_view", [])
            identifier = entities.get("identifier")
            
            # 先尝试 part_code
            display_item = DataViewBuilder.find_by_part_code(display_view, identifier)
            
            # 如果没找到，尝试 subgraph_id
            if not display_item:
                display_item = DataViewBuilder.find_by_subgraph_id(display_view, identifier)
            
            if display_item:
                logger.info(f"✅ 找到记录: part_code={display_item.get('part_code')}")
                
                # 构建展示层修改
                display_changes = [{
                    "part_code": display_item["part_code"],
                    "field": entities["field"],
                    "value": entities["value"]
                }]
                
                # 反向映射到存储层
                raw_data = context.get("raw_data") or context
                table_changes = DataViewBuilder.map_display_to_tables(
                    display_changes,
                    raw_data
                )
                
                logger.info(f"✅ 反向映射完成: {len(table_changes)} 个表修改")
                return table_changes
        
        # 🆕 检查是否包含概念词
        concept_keyword_result = await self._try_concept_keyword_matching(text, context)
        if concept_keyword_result:
            logger.info(f"✅ 概念词匹配成功: {len(concept_keyword_result)} 个修改")
            return concept_keyword_result
        
        # 🆕 实体提取失败，尝试智能匹配
        logger.info("🔍 实体提取失败，尝试智能匹配...")
        try:
            smart_match_result = await self._try_smart_matching(text, context)
            if smart_match_result:
                logger.info(f"✅ 智能匹配成功: {len(smart_match_result)} 个修改")
                return smart_match_result
        except NeedsConfirmationException:
            # 重新抛出确认异常
            raise
        except Exception as e:
            logger.warning(f"⚠️  智能匹配失败: {e}")
        
        # 回退到 LLM 解析
        logger.info("🤖 回退到 LLM 解析...")
        
        if self.use_llm:
            try:
                # 🆕 将 user_input 和 display_view 添加到 context
                context_with_input = {
                    **context,  # 保留完整的 context（包括 display_view）
                    "user_input": text
                }
                changes = await self._parse_with_llm(text, context_with_input)
                if changes:
                    logger.info(f"✅ LLM 解析成功: {len(changes)} 个修改")
                    return changes
            except httpx.TimeoutException as e:
                logger.error(f"❌ LLM 解析超时（{self.llm_timeout}秒）: {str(e)}", exc_info=True)
            except Exception as e:
                logger.error(f"❌ LLM 解析失败: {type(e).__name__} - {str(e)}", exc_info=True)
        
        # 最后回退到规则解析
        logger.warning("⚠️  回退到规则解析")
        return await self._parse_with_rules(text, context)
    
    async def _extract_entities_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        从文本中提取实体
        
        Args:
            text: 用户输入
        
        Returns:
            实体字典 {"identifier": "LP-02", "field": "length_mm", "value": "100"}
        """
        # 🆕 识别更多 part_code 模式
        # 支持: P001, P-001, LP-02, PART001, 零件01 等
        part_code_patterns = [
            r'[Ll][Pp][-_]?\d{2,}',      # LP-02, lp02, LP_02
            r'[Pp][-_]?\d{3,}',          # P001, P-001, p_001
            r'PART[-_]?\d{3,}',          # PART001, PART-001
            r'零件[-_]?\d{2,}'            # 零件01, 零件-01
        ]
        
        identifier = None
        for pattern in part_code_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                identifier = match.group()
                logger.info(f"🔍 提取到标识符: {identifier}")
                break
        
        # 如果没找到 part_code，尝试 subgraph_id
        if not identifier:
            subgraph_id_pattern = r'subgraph[_-]?\d+'
            subgraph_id_match = re.search(subgraph_id_pattern, text, re.IGNORECASE)
            if subgraph_id_match:
                identifier = subgraph_id_match.group()
                logger.info(f"🔍 提取到 subgraph_id: {identifier}")
        
        if not identifier:
            logger.warning(f"⚠️  未能提取标识符: {text}")
            return None
        
        # 🆕 改进字段识别（支持更多模式）
        # ⚠️ 重要：复合词必须放在前面，避免被部分匹配
        field_patterns = {
            r'材质价格|材质单价|材料价格|材料单价|material[_\s]?price|material[_\s]?unit[_\s]?price': 'material_unit_price',  # 材质价格/单价（复合词优先）
            r'工艺价格|工艺单价|process[_\s]?price|process[_\s]?unit[_\s]?price': 'process_unit_price',    # 工艺价格/单价（复合词优先）
            r'材料|材质|material': 'material',
            r'长度|length': 'length_mm',
            r'宽度|width': 'width_mm',
            r'厚度|thickness': 'thickness_mm',
            r'数量|quantity|qty': 'quantity',
            r'工艺|process': 'process_code',
            r'重量|weight': 'weight_kg',
            r'价格|单价|price': 'price'
        }
        
        field = None
        for pattern, field_name in field_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                field = field_name
                logger.info(f"🔍 识别到字段: {field}")
                break
        
        if not field:
            logger.warning(f"⚠️  未能识别字段: {text}")
            return None
        
        # 🆕 改进值提取（支持更多模式）
        # 模式1: "改为/改成/修改为/设置为 XXX"
        value_patterns = [
            r'(?:改为|改成|修改为|设置为|变为|换成)\s*([^\s，。、]+)',
            r'(?:为|是)\s*([^\s，。、]+)',  # "长度为100"
            r'=\s*([^\s，。、]+)'            # "长度=100"
        ]
        
        value = None
        for pattern in value_patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                logger.info(f"🔍 提取到值: {value}")
                break
        
        # 如果还没找到，尝试提取数字（针对尺寸字段）
        if not value and field in ['length_mm', 'width_mm', 'thickness_mm', 'quantity', 'weight_kg']:
            number_match = re.search(r'\d+(?:\.\d+)?', text)
            if number_match:
                value = number_match.group()
                logger.info(f"🔍 提取到数字值: {value}")
        
        if not value:
            logger.warning(f"⚠️  未能提取值: {text}")
            return None
        
        logger.info(f"✅ 实体提取成功: identifier={identifier}, field={field}, value={value}")
        return {
            "identifier": identifier,
            "field": field,
            "value": value
        }
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.http_client.aclose()
        logger.info("✅ NLPParser 已关闭")
    
    async def _parse_process_modification(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        解析工艺修改
        
        🆕 策略：直接使用 LLM 解析（LLM 优先策略）
        
        理由：
        1. 准确性最重要：工艺修改是重要操作，错误代价高
        2. 支持各种表达方式：不需要维护关键词列表
        3. 维护成本低：代码简单，易理解
        4. 用户体验好：更智能，更人性化
        
        性能：
        - LLM 解析：~3秒
        - 正则解析：~5毫秒
        - 权衡：准确性 > 性能（工艺修改不频繁）
        
        支持的表达方式：
        - "材质为Cr12mov的工艺改为慢丝割一修二"
        - "材质是45#的工艺改为慢丝割一修二" ✅
        - "材质等于SKD11的工艺改为慢丝割一修二" ✅
        - "45#材质的零件工艺改为慢丝割一修二" ✅
        - "用45#材质的零件工艺改为慢丝割一修二" ✅
        
        Args:
            text: 用户输入
            context: 数据上下文
        
        Returns:
            修改列表
        """
        try:
            logger.info(f"🔧 解析工艺修改: {text}")
            logger.info(f"🤖 使用 LLM 解析（LLM 优先策略：准确性 > 性能）")
            
            # 直接使用 LLM 解析
            context_with_input = {**context, "user_input": text}
            return await self._parse_with_llm(text, context_with_input)
        
        except Exception as e:
            logger.error(f"❌ 解析工艺修改失败: {e}", exc_info=True)
            return []
    
    def _calculate_complexity(self, text: str) -> int:
        """
        计算句子复杂度
        
        复杂度指标：
        - 多个"把"字（复合句式）：+5 分（强信号）
        - 🆕 筛选条件关键词（如"开头"、"结尾"、"包含"）：+5 分（需要语义理解）
        - 🆕 多个零件关键词连写（无分隔符）+ "都"/"全部"：+5 分（需要智能分词）
        - 多个逗号/顿号（复合句式）：+4 分（2个及以上）
        - 多个"和"字（多个零件）：+2 分（3个及以上）
        - 多个"类"字（多个类型）：+2 分（3个及以上）
        - 零件编号列举（如"DIE-04、DIE-03、PH2-04"）：+2 分（3个及以上）
        - 组合加分：同时有多个"和"字(>=3)和多个"类"字(>=4)：+1 分
        - 长度超过40字符：+1 分
        
        阈值：
        - < 5: 简单句式，使用正则
        - >= 5: 复杂句式，使用 LLM
        
        Args:
            text: 用户输入
        
        Returns:
            复杂度分数
        """
        score = 0
        
        # 检查1：多个"把"字（最强信号）
        ba_count = text.count('把')
        if ba_count > 1:
            score += 5
            logger.debug(f"🔍 检测到 {ba_count} 个'把'字，+5 分")
        
        # 🆕 检查1.5：筛选条件关键词（需要语义理解）
        # 如："UB开头"、"以UP结尾"、"包含DIE"、"不包含"、"材质为Cr12"、"材质是45#"等
        # ⚠️ 注意："XX类的零件"不算筛选条件，这是正常的类型修改
        filter_keywords = ['开头', '结尾', '包含', '不包含', '以', '材质为', '材料为', '尺寸为', '材质是', '材料是', '尺寸是']
        has_filter = any(keyword in text for keyword in filter_keywords)
        
        # 🆕 特殊检测："这些零件"、"那些零件"（但不包括"XX类的零件"）
        if not has_filter:
            # 检查是否有"这些零件"或"那些零件"
            if ('这些' in text or '那些' in text) and '零件' in text:
                has_filter = True
            # 检查是否有"XX的零件"但不是"XX类的零件"
            elif '的零件' in text and '类的零件' not in text:
                has_filter = True
        
        if has_filter:
            score += 5
            logger.debug(f"🔍 检测到筛选条件关键词，+5 分")
        
        # 🆕 检查1.6：多个零件关键词连写（无分隔符）+ "都"/"全部"
        # 如："冲头刀口入块都改成..."（需要智能分词）
        if "都" in text or "全部" in text:
            # 提取"都"或"全部"之前的部分
            import re
            before_all = re.split(r'都|全部', text)[0]
            
            # 检查是否包含多个零件关键词（连写，无逗号、顿号、空格、"和"字）
            # 且长度 > 4（排除"模板都"这种单个关键词的情况）
            if not re.search(r'[,，、\s和]', before_all) and len(before_all) > 4:
                score += 5  # 🔧 从 +3 改为 +5，确保触发 LLM
                logger.debug(f"🔍 检测到多个零件关键词连写（'{before_all}'），+5 分")
        
        # 检查2：多个逗号/顿号（支持中英文逗号和顿号）
        comma_count = text.count('，') + text.count(',') + text.count('、')
        if comma_count >= 2:
            score += 4
            logger.debug(f"🔍 检测到 {comma_count} 个逗号/顿号，+4 分")
        
        # 检查3：多个"和"字（3个及以上才算复杂）
        and_count = text.count('和')
        if and_count >= 3:
            score += 2
            logger.debug(f"🔍 检测到 {and_count} 个'和'字，+2 分")
        
        # 检查4：多个"类"字（3个及以上才算复杂）
        type_count = text.count('类')
        if type_count >= 3:
            score += 2
            logger.debug(f"🔍 检测到 {type_count} 个'类'字，+2 分")
        
        # 🆕 检查4.5：零件编号列举（如"DIE-04、DIE-03、PH2-04"）
        # 匹配模式：字母+数字+连字符+数字（如 DIE-04, LP-02, PH2-04）
        import re
        part_code_pattern = r'[A-Z]+[-_]?\d+'
        part_codes = re.findall(part_code_pattern, text, re.IGNORECASE)
        if len(part_codes) >= 3:
            score += 2
            logger.debug(f"🔍 检测到 {len(part_codes)} 个零件编号列举，+2 分")
        
        # 检查5：组合加分（多个"和"字 + 多个"类"字）
        # 这种组合通常表示"A类和B类和C类和D类"，是复杂句式
        if and_count >= 3 and type_count >= 4:
            score += 1
            logger.debug(f"🔍 检测到多个'和'字({and_count})和多个'类'字({type_count})的组合，+1 分")
        
        # 检查6：长度（超过40字符）
        if len(text) > 40:
            score += 1
            logger.debug(f"🔍 文本长度 {len(text)} > 40，+1 分")
        
        return score
    
    def _contains_process_keywords(self, part_name: str) -> bool:
        """
        检查零件名称是否包含工艺关键词
        
        如果包含，说明正则匹配可能有误（把工艺关键词包含在零件名称中了）
        
        Args:
            part_name: 零件名称
        
        Returns:
            是否包含工艺关键词
        """
        # 工艺关键词列表
        process_keywords = [
            '线割', '工艺', '方式',
            '慢丝', '快丝', '中丝',
            '割一', '修一', '修二', '修三',
            '热处理', '磨削', '铣削'
        ]
        
        # 检查是否以工艺关键词结尾（最常见的错误）
        for keyword in process_keywords:
            if part_name.endswith(keyword):
                logger.debug(f"🔍 零件名称以工艺关键词结尾: {part_name} (关键词: {keyword})")
                return True
        
        return False
    
    def _extract_process_modification_entities(self, text: str) -> tuple:
        """
        从文本中提取零件名称和工艺描述
        
        Args:
            text: 用户输入
        
        Returns:
            (part_names, process_desc) 元组
            - part_names: 可以是单个字符串、"ALL"、或逗号分隔的多个零件名
            - process_desc: 工艺描述
        """
        # 🆕 模式0.5: "XX类的零件全部改成 工艺描述"（批量修改特定类型）
        # ⚠️ 优先级最高！必须在模式0之前匹配
        # 匹配: "下模板类的零件全部改成中丝割一修一"
        pattern0_5 = r'(.+?类)(?:的)?零件\s*全部\s*(?:改为|改成|修改为|设置为)\s*(.+)'
        match = re.search(pattern0_5, text)
        if match:
            part_type = match.group(1).strip()  # "下模板类"
            process_desc = match.group(2).strip()
            # 返回类型标识，后续会根据类型筛选零件
            logger.info(f"🔍 匹配到类型筛选模式: {part_type}")
            return (part_type, process_desc)
        
        # 🆕 模式0.6: "XX类的零件工艺改成 工艺描述"（批量修改特定类型，不带"全部"）
        # ⚠️ 优先级高于模式1，避免提取出"XX类的零件"
        # 匹配: "下模板类的零件工艺改成慢丝割一修二"
        pattern0_6 = r'(.+?类)(?:的)?零件\s*(?:的)?(?:线割工艺|工艺|线割方式)\s*(?:改为|改成|修改为|设置为)\s*(.+)'
        match = re.search(pattern0_6, text)
        if match:
            part_type = match.group(1).strip()  # "下模板类"
            process_desc = match.group(2).strip()
            # 返回类型标识，后续会根据类型筛选零件
            logger.info(f"🔍 匹配到类型筛选模式（不带全部）: {part_type}")
            return (part_type, process_desc)
        
        # 🆕 模式0: "全部工艺改为 工艺描述"（真正的全部修改）
        # ⚠️ 必须在开头匹配"全部/所有/全体"，避免误匹配
        pattern0 = r'^(?:全部|所有|全体|这套)\s*(?:的)?(?:线割工艺|工艺|线割方式)?\s*(?:改为|改成|修改为|设置为|都改成)\s*(.+)'
        match = re.search(pattern0, text)
        if match:
            process_desc = match.group(1).strip()
            logger.info(f"🔍 匹配到全部修改模式")
            return ("ALL", process_desc)
        
        # 🆕 模式0.8: "把 零件名 的工艺改成 工艺描述"（口语化句式）
        # ⚠️ 优先级高于模式1，避免"把"字被包含在零件名中
        # 匹配: "把LP-02的工艺改成慢丝割一修一" 或 "把LP-02，PH2-04的工艺改成慢丝割一修一"
         # 匹配: "把所有的工艺改为慢丝割一修一"
        pattern0_8 = r'把\s*(.+?)\s*(?:的)?(?:线割工艺|工艺|线割方式)\s*(?:改为|改成|修改为|设置为)\s*(.+)'
        match = re.search(pattern0_8, text)
        if match:
            part_names_str = match.group(1).strip()
            process_desc = match.group(2).strip()
            logger.info(f"🔍 匹配到口语化模式（把...）")
            
            # 🆕 检查是否为"全部"关键词
            if part_names_str in ['全部', '所有', '全体', '这套', '所有的', '全部的', '全体的', '这套的']:
                logger.info(f"🔍 识别到全部关键词: {part_names_str} → ALL")
                return ("ALL", process_desc)
            
            return (part_names_str, process_desc)
        
        # 🆕 模式1: "零件名1, 零件名2 工艺改为 工艺描述"（支持多个零件）
        # 匹配: DIE-03, DIE-04工艺改为中丝割一修一
        # 匹配: 上垫脚类工艺为慢丝割一修三
        # 匹配: 上插刀类线割工艺改为慢丝割一修二
        # ⚠️ 修复：使用更精确的匹配，避免在"工艺"的"工"字处截断
        pattern1 = r'(.+?)\s*(?:的)?(?:线割工艺|工艺|线割方式)\s*(?:改为|改成|修改为|设置为|为)\s*(.+)'
        match = re.search(pattern1, text)
        if match:
            part_names_str = match.group(1).strip()
            process_desc = match.group(2).strip()
            # 排除"全部"、"所有"等关键词（已在模式0处理）
            if part_names_str not in ['全部', '所有', '全体', '这套']:
                return (part_names_str, process_desc)
        
        # 模式2: "将 零件名 的工艺改为 工艺描述"
        # ⚠️ 修复：使用非捕获组 (?:将\s+) 来匹配"将"字，但不包含在捕获组中
        pattern2 = r'(?:将\s+)(.+?)\s*(?:的)?(?:线割工艺|工艺|线割方式)\s*(?:改为|改成)\s*(.+)'
        match = re.search(pattern2, text)
        if match:
            part_names_str = match.group(1).strip()
            process_desc = match.group(2).strip()
            
            # 🆕 检查是否为"全部"关键词
            if part_names_str in ['全部', '所有', '全体', '这套', '所有的', '全部的', '全体的', '这套的']:
                logger.info(f"🔍 识别到全部关键词: {part_names_str} → ALL")
                return ("ALL", process_desc)
            
            return (part_names_str, process_desc)
        
        # 模式3: "修改 零件名 工艺为 工艺描述"
        # ⚠️ 修复：使用非捕获组 (?:修改\s+) 来匹配"修改"字，但不包含在捕获组中
        pattern3 = r'(?:修改\s+)(.+?)\s*(?:的)?(?:线割工艺|工艺|线割方式)\s*为\s*(.+)'
        match = re.search(pattern3, text)
        if match:
            part_names_str = match.group(1).strip()
            process_desc = match.group(2).strip()
            
            # 🆕 检查是否为"全部"关键词
            if part_names_str in ['全部', '所有', '全体', '这套', '所有的', '全部的', '全体的', '这套的']:
                logger.info(f"🔍 识别到全部关键词: {part_names_str} → ALL")
                return ("ALL", process_desc)
            
            return (part_names_str, process_desc)
        
        return (None, None)
    
    async def _query_process_rules(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        查询 process_rules 表
        
        Args:
            description: 工艺描述
            context: 上下文（需要包含 db_session）
        
        Returns:
            工艺规则字典，如果没找到返回 None
        """
        try:
            # 从上下文获取 db_session
            db_session = context.get("db_session")
            
            if not db_session:
                logger.warning("⚠️  上下文中没有 db_session，无法查询 process_rules")
                return None
            
            # 使用 ProcessRulesRepository 查询
            from api_gateway.repositories.process_rules_repository import ProcessRulesRepository
            
            repo = ProcessRulesRepository()
            rule = await repo.find_wire_process_by_description(db_session, description)
            
            return rule
        
        except Exception as e:
            logger.error(f"❌ 查询 process_rules 失败: {e}", exc_info=True)
            return None


    
    def _apply_contains_filter(
        self,
        change: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        应用包含匹配过滤器（支持概念词自动展开）
        
        Args:
            change: 包含 filter 的修改指令
            context: 数据上下文
        
        Returns:
            展开后的修改列表（每个匹配的零件一个修改）
        """
        filter_conditions = change.get("filter", {})
        keyword = filter_conditions.get("part_name_contains")
        
        if not keyword:
            logger.warning("⚠️  filter 中缺少 part_name_contains")
            return []
        
        # 获取 display_view
        display_view = context.get("display_view", [])
        
        if not display_view:
            logger.warning("⚠️  context 中没有 display_view，无法进行包含匹配")
            return []
        
        # 🆕 调试：输出 display_view 的大小和前几个零件名称
        logger.info(f"📊 display_view 包含 {len(display_view)} 个零件")
        if display_view:
            sample_names = [item.get("part_name", "N/A") for item in display_view[:5]]
            logger.info(f"📋 前5个零件名称: {sample_names}")
        
        # 🆕 检查是否为概念词，如果是则展开为多个关键词
        from agents.action_handlers.base_handler import BaseActionHandler
        keywords = BaseActionHandler.CONCEPT_KEYWORD_MAPPING.get(keyword, [keyword])
        
        if len(keywords) > 1:
            logger.info(f"✅ 概念词展开: {keyword} → {keywords}")
        
        # 🆕 对每个关键词进行包含匹配
        all_matched_items = []
        matched_by_keyword = {}  # 记录每个关键词匹配到的零件
        
        for kw in keywords:
            matched_items = []
            for item in display_view:
                part_name = item.get("part_name", "")
                part_code = item.get("part_code", "")
                # 🆕 不区分大小写的匹配（同时匹配 part_name 和 part_code）
                if kw.upper() in part_name.upper() or kw.upper() in part_code.upper():
                    matched_items.append(item)
                    logger.debug(f"✅ 包含匹配: {part_name} ({part_code}) (关键词: {kw})")
            
            if matched_items:
                all_matched_items.extend(matched_items)
                matched_by_keyword[kw] = len(matched_items)
                logger.info(f"✅ 关键词 '{kw}' 匹配到 {len(matched_items)} 个零件")
            else:
                logger.warning(f"⚠️  关键词 '{kw}' 未匹配到任何零件")
                matched_by_keyword[kw] = 0
        
        # 🆕 去重（一个零件可能被多个关键词匹配到）
        seen_subgraph_ids = set()
        unique_matched_items = []
        for item in all_matched_items:
            source = item.get("_source", {})
            subgraph_id = source.get("subgraph_id")
            if subgraph_id and subgraph_id not in seen_subgraph_ids:
                seen_subgraph_ids.add(subgraph_id)
                unique_matched_items.append(item)
        
        if not unique_matched_items:
            logger.warning(f"⚠️  关键词 '{keyword}' 未匹配到任何零件")
            return []
        
        # 🆕 如果是概念词，显示详细的匹配摘要
        if len(keywords) > 1:
            summary_parts = [f"{kw}: {count}个" for kw, count in matched_by_keyword.items()]
            logger.info(f"✅ 概念词 '{keyword}' 匹配到 {len(unique_matched_items)} 个零件（{', '.join(summary_parts)}）")
        else:
            logger.info(f"✅ 关键词 '{keyword}' 匹配到 {len(unique_matched_items)} 个零件")
        
        # 展开为具体的修改操作
        expanded_changes = []
        for item in unique_matched_items:
            source = item.get("_source", {})
            subgraph_id = source.get("subgraph_id")
            
            if not subgraph_id:
                continue
            
            # 🆕 根据表名选择正确的 ID
            table = change["table"]
            if table == "features":
                # features 表使用 feature_id
                record_id = source.get("feature_id")
                if not record_id:
                    logger.warning(f"⚠️  零件 {item.get('part_name')} 缺少 feature_id，跳过")
                    continue
            elif table == "subgraphs":
                # subgraphs 表使用 subgraph_id
                record_id = subgraph_id
            elif table == "job_price_snapshots":
                # job_price_snapshots 表使用 snapshot_id
                # 根据字段判断是 wire 还是 material
                if change["field"] == "price":
                    # 需要根据上下文判断是修改工艺价格还是材质价格
                    # 这里暂时使用 subgraph_id（后续会在验证时处理）
                    record_id = subgraph_id
                else:
                    record_id = subgraph_id
            else:
                # 其他表使用 subgraph_id
                record_id = subgraph_id
            
            # 生成修改操作
            expanded_changes.append({
                "table": table,
                "id": record_id,
                "field": change["field"],
                "value": change["value"],
                "original_text": change.get("original_text", ""),
                "matched_by_keyword": keyword  # 记录原始关键词（可能是概念词）
            })
        
        return expanded_changes

    def _apply_material_filter(
        self,
        change: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        应用材质筛选过滤器
        
        Args:
            change: 包含 filter 的修改指令
            context: 数据上下文
        
        Returns:
            展开后的修改列表（每个匹配的零件一个修改）
        """
        filter_conditions = change.get("filter", {})
        material = filter_conditions.get("material_equals")
        
        if not material:
            logger.warning("⚠️  filter 中缺少 material_equals")
            return []
        
        # 获取 display_view
        display_view = context.get("display_view", [])
        
        if not display_view:
            logger.warning("⚠️  context 中没有 display_view，无法进行材质匹配")
            return []
        
        logger.info(f"🔍 按材质筛选: {material}")
        
        # 材质匹配（不区分大小写）
        matched_items = []
        for item in display_view:
            item_material = item.get("material", "")
            # 不区分大小写的匹配
            if item_material.upper() == material.upper():
                matched_items.append(item)
                logger.debug(f"✅ 材质匹配: {item.get('part_name')} ({item.get('part_code')}) - 材质: {item_material}")
        
        if not matched_items:
            logger.warning(f"⚠️  材质 '{material}' 未匹配到任何零件")
            return []
        
        logger.info(f"✅ 材质 '{material}' 匹配到 {len(matched_items)} 个零件")
        
        # 展开为具体的修改操作
        expanded_changes = []
        for item in matched_items:
            source = item.get("_source", {})
            subgraph_id = source.get("subgraph_id")
            
            if not subgraph_id:
                continue
            
            # 根据表名选择正确的 ID
            table = change["table"]
            if table == "features":
                record_id = source.get("feature_id")
                if not record_id:
                    logger.warning(f"⚠️  零件 {item.get('part_name')} 缺少 feature_id，跳过")
                    continue
            elif table == "subgraphs":
                record_id = subgraph_id
            else:
                record_id = subgraph_id
            
            # 生成修改操作
            expanded_changes.append({
                "table": table,
                "id": record_id,
                "field": change["field"],
                "value": change["value"],
                "original_text": change.get("original_text", ""),
                "matched_by_material": material
            })
        
        return expanded_changes

    def _apply_dimension_filter(
        self,
        change: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        应用尺寸筛选过滤器
        
        Args:
            change: 包含 filter 的修改指令
            context: 数据上下文
        
        Returns:
            展开后的修改列表（每个匹配的零件一个修改）
        """
        filter_conditions = change.get("filter", {})
        dimension = filter_conditions.get("dimension_equals")
        
        if not dimension:
            logger.warning("⚠️  filter 中缺少 dimension_equals")
            return []
        
        # 获取 display_view
        display_view = context.get("display_view", [])
        
        if not display_view:
            logger.warning("⚠️  context 中没有 display_view，无法进行尺寸匹配")
            return []
        
        logger.info(f"🔍 按尺寸筛选: {dimension}")
        
        # 解析尺寸（支持多种分隔符）
        import re
        parts = re.split(r'[*×xX]', dimension)
        if len(parts) != 3:
            logger.warning(f"⚠️  尺寸格式不正确: {dimension}（应为 长*宽*厚）")
            return []
        
        try:
            target_length = float(parts[0].strip())
            target_width = float(parts[1].strip())
            target_thickness = float(parts[2].strip())
        except ValueError:
            logger.warning(f"⚠️  尺寸解析失败: {dimension}")
            return []
        
        # 尺寸匹配
        matched_items = []
        for item in display_view:
            length = item.get("length", 0) or 0
            width = item.get("width", 0) or 0
            thickness = item.get("thickness", 0) or 0
            
            # 精确匹配（允许小误差）
            if (abs(length - target_length) < 0.01 and
                abs(width - target_width) < 0.01 and
                abs(thickness - target_thickness) < 0.01):
                matched_items.append(item)
                logger.debug(f"✅ 尺寸匹配: {item.get('part_name')} ({item.get('part_code')}) - {length}×{width}×{thickness}")
        
        if not matched_items:
            logger.warning(f"⚠️  尺寸 '{dimension}' 未匹配到任何零件")
            return []
        
        logger.info(f"✅ 尺寸 '{dimension}' 匹配到 {len(matched_items)} 个零件")
        
        # 展开为具体的修改操作
        expanded_changes = []
        for item in matched_items:
            source = item.get("_source", {})
            subgraph_id = source.get("subgraph_id")
            
            if not subgraph_id:
                continue
            
            # 根据表名选择正确的 ID
            table = change["table"]
            if table == "features":
                record_id = source.get("feature_id")
                if not record_id:
                    logger.warning(f"⚠️  零件 {item.get('part_name')} 缺少 feature_id，跳过")
                    continue
            elif table == "subgraphs":
                record_id = subgraph_id
            else:
                record_id = subgraph_id
            
            # 生成修改操作
            expanded_changes.append({
                "table": table,
                "id": record_id,
                "field": change["field"],
                "value": change["value"],
                "original_text": change.get("original_text", ""),
                "matched_by_dimension": dimension
            })
        
        return expanded_changes


    
    # ==================== Concept Keyword Matching ====================
    
    async def _try_concept_keyword_matching(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        尝试使用概念词匹配解析用户输入
        
        检测用户输入中是否包含概念词（如"冲头类"、"模架"等），
        如果包含，则展开为多个关键词并进行匹配
        
        Args:
            text: 用户输入
            context: 数据上下文
        
        Returns:
            解析后的修改列表，如果不包含概念词则返回 None
        """
        from agents.action_handlers.base_handler import BaseActionHandler
        
        # 定义概念词列表
        concept_keywords = list(BaseActionHandler.CONCEPT_KEYWORD_MAPPING.keys())
        
        # 检查用户输入中是否包含概念词
        detected_concept = None
        for concept in concept_keywords:
            if concept in text:
                detected_concept = concept
                logger.info(f"🔍 检测到概念词: {concept}")
                break
        
        if not detected_concept:
            # 没有检测到概念词
            return None
        
        # 提取字段和值
        field = None
        value = None
        
        # 识别字段
        field_patterns = {
            r'材料|材质|material': 'material',
            r'工艺|process': 'process_code',
            r'长度|length': 'length_mm',
            r'宽度|width': 'width_mm',
            r'厚度|thickness': 'thickness_mm',
        }
        
        for pattern, field_name in field_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                field = field_name
                logger.info(f"🔍 识别到字段: {field}")
                break
        
        if not field:
            logger.warning(f"⚠️  未能识别字段: {text}")
            return None
        
        # 提取值
        value_patterns = [
            r'(?:改为|改成|修改为|设置为|变为|换成)\s*([^\s，。、]+)',
            r'(?:为|是)\s*([^\s，。、]+)',
        ]
        
        for pattern in value_patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                logger.info(f"🔍 提取到值: {value}")
                break
        
        if not value:
            logger.warning(f"⚠️  未能提取值: {text}")
            return None
        
        # 获取 display_view
        display_view = context.get("display_view")
        if not display_view:
            logger.warning("⚠️  无法获取 display_view")
            return None
        
        # 展开概念词为关键词列表
        concept_mapping = BaseActionHandler.CONCEPT_KEYWORD_MAPPING
        keywords = concept_mapping.get(detected_concept)
        
        if not keywords:
            logger.warning(f"⚠️  概念词 '{detected_concept}' 未在映射表中")
            return None
        
        logger.info(f"✅ 概念词 '{detected_concept}' 展开为: {keywords}")
        
        # 使用关键词匹配零件
        matched_subgraph_ids = []
        seen = set()
        
        for keyword in keywords:
            for item in display_view:
                part_name = item.get("part_name", "")
                if keyword in part_name:
                    source = item.get("_source", {})
                    subgraph_id = source.get("subgraph_id")
                    if subgraph_id and subgraph_id not in seen:
                        seen.add(subgraph_id)
                        matched_subgraph_ids.append(subgraph_id)
                        logger.debug(f"✅ 匹配: {part_name} (关键词: {keyword}, ID: {subgraph_id})")
        
        if not matched_subgraph_ids:
            logger.warning(f"⚠️  概念词 '{detected_concept}' 未匹配到任何零件")
            return None
        
        logger.info(f"✅ 概念词 '{detected_concept}' 匹配到 {len(matched_subgraph_ids)} 个零件")
        
        # 构建修改列表
        changes = []
        for subgraph_id in matched_subgraph_ids:
            changes.append({
                "table": self._infer_table_from_field(field),
                "id": subgraph_id,
                "field": field,
                "value": value,
                "original_text": text
            })
        
        return changes
    
    # ==================== Smart Matching Integration ====================
    
    async def _try_smart_matching(
        self,
        text: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        尝试使用智能匹配解析用户输入
        
        当常规解析失败时调用此方法，使用智能匹配器尝试找到用户想要修改的目标
        
        Args:
            text: 用户输入
            context: 数据上下文
        
        Returns:
            解析后的修改列表
        
        Raises:
            NeedsConfirmationException: 当找到多个候选时
        """
        from shared.input_normalizer import InputNormalizer
        from shared.smart_matcher import SmartMatcher
        from shared.match_evaluator import MatchEvaluator
        
        logger.info("🔍 使用智能匹配解析用户输入...")
        
        # 1. 获取或构建 display_view
        display_view = context.get("display_view")
        
        if not display_view:
            # 如果没有 display_view，从 raw_data 构建
            logger.info("📋 构建 display_view...")
            from agents.data_view_builder import DataViewBuilder
            raw_data = context.get("raw_data") or context
            display_view = DataViewBuilder.build_display_view(raw_data)
        
        if not display_view:
            logger.warning("⚠️  无法获取 display_view")
            return []
        
        # 2. 🆕 使用 LLM 提取实体（替换复杂的正则）
        entities = await self._extract_entities_with_llm(text)
        
        if not entities:
            logger.warning("⚠️  LLM 未能提取实体")
            return []
        
        input_id = entities.get("part_id")
        material = entities.get("material")
        dimension = entities.get("dimension")
        field = entities.get("field")
        value = entities.get("value")
        # 🆕 提取前缀/后缀/包含模式
        part_code_prefix = entities.get("part_code_prefix")
        part_code_suffix = entities.get("part_code_suffix")
        part_code_contains = entities.get("part_code_contains")
        
        logger.info(f"🔍 LLM 提取结果: part_id={input_id}, material={material}, dimension={dimension}, field={field}, value={value}")
        if part_code_prefix or part_code_suffix or part_code_contains:
            logger.info(f"🔍 模式匹配: prefix={part_code_prefix}, suffix={part_code_suffix}, contains={part_code_contains}")
        
        if not input_id and not material and not dimension and not part_code_prefix and not part_code_suffix and not part_code_contains:
            logger.warning("⚠️  无法从输入中提取有效信息")
            return []
        
        # 3. 使用智能匹配器
        matcher = SmartMatcher(display_view)
        matches = []
        
        # 按优先级尝试不同的匹配策略
        # 🆕 优先处理前缀/后缀/包含模式
        if part_code_prefix:
            # 前缀匹配：找到所有 part_code 以指定前缀开头的零件
            logger.info(f"🔍 使用前缀匹配: {part_code_prefix}")
            matches = matcher.match_by_part_code(part_code_prefix, fuzzy=True)
            logger.info(f"📊 前缀匹配: {len(matches)} 个结果")
        
        elif part_code_suffix:
            # 后缀匹配：找到所有 part_code 以指定后缀结尾的零件
            logger.info(f"🔍 使用后缀匹配: {part_code_suffix}")
            for item in display_view:
                part_code = item.get("part_code", "")
                if part_code and part_code.upper().endswith(part_code_suffix.upper()):
                    matches.append(item)
            logger.info(f"📊 后缀匹配: {len(matches)} 个结果")
        
        elif part_code_contains:
            # 包含匹配：找到所有 part_code 包含指定字符串的零件
            logger.info(f"🔍 使用包含匹配: {part_code_contains}")
            for item in display_view:
                part_code = item.get("part_code", "")
                if part_code and part_code_contains.upper() in part_code.upper():
                    matches.append(item)
            logger.info(f"📊 包含匹配: {len(matches)} 个结果")
        
        elif input_id:
            # 优先使用子图ID匹配（模糊匹配）
            matches = matcher.match_by_subgraph_id(input_id, fuzzy=True)
            logger.info(f"📊 子图ID匹配: {len(matches)} 个结果")
        
        elif material:
            # 尝试材质匹配
            matches = matcher.match_by_material(material)
            logger.info(f"📊 材质匹配: {len(matches)} 个结果")
        
        elif dimension:
            # 尝试尺寸匹配
            normalizer = InputNormalizer()
            dim_dict = normalizer.normalize_dimension(dimension)
            if dim_dict:
                matches = matcher.match_by_dimension(
                    dim_dict['length'],
                    dim_dict['width'],
                    dim_dict['thickness']
                )
                logger.info(f"📊 尺寸匹配: {len(matches)} 个结果")
        
        # 4. 评估匹配结果
        evaluator = MatchEvaluator()
        evaluation = evaluator.evaluate(matches, text, context)
        
        logger.info(f"📊 匹配评估: status={evaluation.status}, confidence={evaluation.confidence}, count={len(matches)}")
        
        # 5. 根据评估结果决定行动
        if evaluation.status == "none":
            # 没有匹配
            logger.warning("⚠️  智能匹配未找到目标")
            return []
        
        elif evaluation.status in ["unique", "multiple"]:
            # 唯一匹配或多个匹配：直接批量修改
            # 使用 LLM 提取的字段和值
            if not field or not value:
                logger.warning("⚠️  无法提取字段和值")
                return []
            
            # 为每个匹配的零件构建修改指令
            changes = []
            for match in matches:
                source = match.get("_source", {})
                subgraph_id = source.get("subgraph_id")
                
                if not subgraph_id:
                    continue
                
                # 🆕 如果是工艺修改，需要同时修改 wire_process 和 wire_process_note
                if field == "wire_process":
                    # 先添加 wire_process 修改
                    changes.append({
                        "table": self._infer_table_from_field(field),
                        "id": subgraph_id,
                        "field": field,
                        "value": self._map_process_description_to_code(value),
                        "original_text": text
                    })
                    # 再添加 wire_process_note 修改
                    changes.append({
                        "table": "subgraphs",
                        "id": subgraph_id,
                        "field": "wire_process_note",
                        "value": self._normalize_process_description(value),
                        "original_text": text
                    })
                else:
                    # 其他字段，正常处理
                    changes.append({
                        "table": self._infer_table_from_field(field),
                        "id": subgraph_id,
                        "field": field,
                        "value": value,
                        "original_text": text
                    })
            
            logger.info(f"✅ 智能匹配生成 {len(changes)} 个修改操作")
            return changes
        
        else:
            # 其他情况
            logger.warning("⚠️  智能匹配未找到目标")
            return []
    
    async def _enhance_with_smart_matching(
        self,
        changes: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        使用智能匹配增强解析结果
        
        检查解析结果中的ID是否明确，如果不明确则使用智能匹配
        
        Args:
            changes: 初步解析的修改列表
            context: 数据上下文
        
        Returns:
            增强后的修改列表
        
        Raises:
            NeedsConfirmationException: 当找到多个候选时
        """
        from shared.input_normalizer import InputNormalizer
        from shared.smart_matcher import SmartMatcher
        from shared.match_evaluator import MatchEvaluator
        
        # 获取或构建 display_view
        display_view = context.get("display_view")
        
        if not display_view:
            from agents.data_view_builder import DataViewBuilder
            raw_data = context.get("raw_data") or context
            display_view = DataViewBuilder.build_display_view(raw_data)
        
        if not display_view:
            logger.warning("⚠️  无法获取 display_view，跳过智能匹配增强")
            return changes
        
        enhanced_changes = []
        matcher = SmartMatcher(display_view)
        evaluator = MatchEvaluator()
        
        for change in changes:
            record_id = change.get("id")
            
            # 检查ID是否需要智能匹配
            # 1. ID为空
            # 2. ID看起来不像标准格式（没有连字符或下划线）
            # 3. ID是小写的（可能需要标准化）
            needs_matching = (
                not record_id or
                (isinstance(record_id, str) and 
                 not re.search(r'[-_]', record_id) and 
                 record_id.islower())
            )
            
            if not needs_matching:
                enhanced_changes.append(change)
                continue
            
            logger.info(f"🔍 ID '{record_id}' 需要智能匹配")
            
            # 使用智能匹配查找
            matches = matcher.match_by_subgraph_id(record_id, fuzzy=True)
            
            evaluation = evaluator.evaluate(matches, change.get("original_text", ""), context)
            
            if evaluation.status == "none":
                # 没有匹配，保持原样
                enhanced_changes.append(change)
                logger.warning(f"⚠️  智能匹配未找到 {record_id}")
            
            elif evaluation.status in ["unique", "multiple"]:
                # 唯一匹配或多个匹配：直接使用第一个匹配（或批量修改）
                if evaluation.status == "unique":
                    # 唯一匹配，更新ID
                    matched_part = matches[0]
                    source = matched_part.get("_source", {})
                    change["id"] = source.get("subgraph_id")
                    enhanced_changes.append(change)
                    logger.info(f"✅ 智能匹配成功: {record_id} → {source.get('subgraph_id')}")
                else:
                    # 多个匹配，为每个匹配生成一个修改操作
                    logger.info(f"✅ 智能匹配找到 {len(matches)} 个候选，批量修改")
                    for match in matches:
                        source = match.get("_source", {})
                        new_change = change.copy()
                        new_change["id"] = source.get("subgraph_id")
                        enhanced_changes.append(new_change)
            
            else:
                # 其他情况，保持原样
                enhanced_changes.append(change)
                logger.warning(f"⚠️  智能匹配未找到 {record_id}")
        
        return enhanced_changes
    
    def _extract_field_and_value(self, text: str) -> tuple:
        """
        从文本中提取字段名和值
        
        Args:
            text: 用户输入
        
        Returns:
            (field, value) 元组
        """
        # 字段模式
        field_patterns = {
            r'材质|材料|material': 'material',
            r'长度|length': 'length_mm',
            r'宽度|width': 'width_mm',
            r'厚度|thickness': 'thickness_mm',
            r'数量|quantity': 'quantity',
            r'工艺|process': 'wire_process'
        }
        
        field = None
        for pattern, field_name in field_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                field = field_name
                break
        
        if not field:
            return (None, None)
        
        # 值模式
        value_patterns = [
            r'(?:改为|改成|修改为|设置为|变为|换成)\s*([^\s，。、]+)',
            r'(?:为|是)\s*([^\s，。、]+)',
            r'=\s*([^\s，。、]+)'
        ]
        
        value = None
        for pattern in value_patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                break
        
        return (field, value)
    
    def _map_process_description_to_code(self, description: str) -> str:
        """
        将工艺描述映射为工艺代码
        
        Args:
            description: 工艺描述（如"慢丝割一修三"）
        
        Returns:
            工艺代码（如"slow_and_three"）
        """
        description = self._normalize_process_description(description)

        # 工艺描述到代码的映射
        process_mapping = {
            # 慢丝
            "慢丝割一修三": "slow_and_three",
            "慢丝割一修二": "slow_and_two",
            "慢丝割一修一": "slow_and_one",
            "慢丝割一刀": "slow_cut",
            "慢丝": "slow_and_one",
            # 中丝
            "中丝割一修一": "middle_and_one",
            "中丝割一刀": "middle_cut",
            "中丝": "middle_and_one",
            # 快丝
            "快丝割一刀": "fast_cut",
            "快丝": "fast_cut",
            # 线割（通用）
            "线割割一修三": "slow_and_three",
            "线割割一修二": "slow_and_two",
            "线割割一修一": "slow_and_one",
            "线割割一刀": "slow_cut"
        }
        
        # 尝试精确匹配
        code = process_mapping.get(description)
        if code:
            return code
        
        # 尝试模糊匹配（去除空格、制表符等）
        normalized_desc = description.replace(" ", "").replace("\t", "").replace("\n", "")
        code = process_mapping.get(normalized_desc)
        if code:
            return code

        if normalized_desc in set(process_mapping.values()):
            return normalized_desc
        
        # 如果没有匹配，返回原始描述（让后续处理）
        logger.warning(f"⚠️  未找到工艺描述 '{description}' 的映射，返回原始值")
        return description

    def _normalize_process_description(self, description: Any) -> Any:
        """
        将线割工艺简称补全为业务默认工艺说明。

        用户自然语言里常会只说“慢丝/中丝/快丝”，落库到 wire_process_note
        时需要保存完整说明，避免后续计价和报表看到不完整工艺。
        """
        if not isinstance(description, str):
            return description

        normalized_desc = description.strip()
        default_mapping = {
            "慢丝": "慢丝割一修一",
            "中丝": "中丝割一修一",
            "快丝": "快丝割一刀",
        }
        return default_mapping.get(normalized_desc, description)

    def _normalize_wire_process_change(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """标准化工艺修改中的 wire_process / wire_process_note 值。"""
        field = change.get("field")

        if field == "wire_process":
            change["value"] = self._map_process_description_to_code(change.get("value"))
        elif field == "wire_process_note":
            change["value"] = self._normalize_process_description(change.get("value"))

        return change
    
    def _infer_table_from_field(self, field: str) -> str:
        """
        根据字段名推断表名
        
        Args:
            field: 字段名
        
        Returns:
            表名
        """
        field_to_table = {
            "material": "features",
            "length_mm": "features",
            "width_mm": "features",
            "thickness_mm": "features",
            "quantity": "features",
            "wire_process": "subgraphs",
            "wire_process_note": "subgraphs",
            "part_name": "subgraphs",
            "part_code": "subgraphs"
        }
        
        return field_to_table.get(field, "subgraphs")
    
    async def _extract_entities_with_llm(self, text: str) -> Dict[str, Any]:
        """
        使用 LLM 提取实体（替换复杂的正则）
        
        Args:
            text: 用户输入（如 "U2-02材质改为Cr12mov"）
        
        Returns:
            {
                "part_id": "U2-02",      # 零件编号（可能为 None）
                "material": "Cr12mov",   # 材质（可能为 None）
                "dimension": None,       # 尺寸（可能为 None）
                "field": "material",     # 字段名
                "value": "Cr12mov",      # 新值
                "part_code_prefix": "B2", # 🆕 前缀匹配（如"B2开头"）
                "part_code_suffix": "01", # 🆕 后缀匹配（如"01结尾"）
                "part_code_contains": "DIE" # 🆕 包含匹配（如"包含DIE"）
            }
        """
        prompt = f"""从以下用户输入中提取信息：

用户输入：{text}

请提取：
1. **零件编号**（part_id）：如 U2-02, PH2-04, B205, DIE-03 等
   - 通常是字母+数字的组合，可能带连字符
   - 不要把材质名称（如 Cr12mov, SKD11, 45#）当成零件编号
   - 如果没有零件编号，返回 null
   - 🆕 如果用户说"XX开头"、"以XX开头"、"XX开头的" → 返回 part_code_prefix="XX"
   - 🆕 如果用户说"XX结尾"、"以XX结尾"、"XX结尾的" → 返回 part_code_suffix="XX"
   - 🆕 如果用户说"包含XX"、"含有XX" → 返回 part_code_contains="XX"

2. **材质**（material）：如 Cr12mov, SKD11, 45#, 718 等
   - 如果用户输入中提到材质，提取出来
   - 如果没有材质，返回 null

3. **尺寸**（dimension）：如 100×50×20, 200*150*30 等
   - 格式：长×宽×厚
   - 如果没有尺寸，返回 null

4. **字段名**（field）：用户想修改的字段
   - 材质/材料 → material
   - 长度 → length_mm
   - 宽度 → width_mm
   - 厚度 → thickness_mm
   - 数量 → quantity
   - 工艺 → wire_process

5. **新值**（value）：用户想设置的新值

返回 JSON 格式：
{{
    "part_id": "零件编号或null",
    "material": "材质或null",
    "dimension": "尺寸或null",
    "field": "字段名",
    "value": "新值",
    "part_code_prefix": "前缀或null",
    "part_code_suffix": "后缀或null",
    "part_code_contains": "包含字符串或null"
}}

示例1：
输入："U2-02材质改为Cr12mov"
输出：
{{
    "part_id": "U2-02",
    "material": "Cr12mov",
    "dimension": null,
    "field": "material",
    "value": "Cr12mov",
    "part_code_prefix": null,
    "part_code_suffix": null,
    "part_code_contains": null
}}

示例2：
输入："PH2-04长度改为100"
输出：
{{
    "part_id": "PH2-04",
    "material": null,
    "dimension": null,
    "field": "length_mm",
    "value": "100",
    "part_code_prefix": null,
    "part_code_suffix": null,
    "part_code_contains": null
}}

示例3：
输入："材质为SKD11的零件数量改为5"
输出：
{{
    "part_id": null,
    "material": "SKD11",
    "dimension": null,
    "field": "quantity",
    "value": "5",
    "part_code_prefix": null,
    "part_code_suffix": null,
    "part_code_contains": null
}}

🆕 示例4（前缀匹配）：
输入："B2开头的材质改为Cr12mov"
输出：
{{
    "part_id": null,
    "material": null,
    "dimension": null,
    "field": "material",
    "value": "Cr12mov",
    "part_code_prefix": "B2",
    "part_code_suffix": null,
    "part_code_contains": null
}}

🆕 示例5（后缀匹配）：
输入："01结尾的零件材质改为718"
输出：
{{
    "part_id": null,
    "material": null,
    "dimension": null,
    "field": "material",
    "value": "718",
    "part_code_prefix": null,
    "part_code_suffix": "01",
    "part_code_contains": null
}}

🆕 示例6（包含匹配）：
输入："包含DIE的零件改为快丝"
输出：
{{
    "part_id": null,
    "material": null,
    "dimension": null,
    "field": "wire_process",
    "value": "快丝",
    "part_code_prefix": null,
    "part_code_suffix": null,
    "part_code_contains": "DIE"
}}

请只返回 JSON，不要其他解释。"""

        try:
            response = await self.http_client.post(
                f"{self.llm_base_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个实体提取助手。你的任务是从用户输入中提取零件编号、材质、尺寸、字段名和新值，以及前缀/后缀/包含匹配模式。"
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                },
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            content = result["choices"][0]["message"]["content"]
            logger.debug(f"🤖 LLM 实体提取响应: {content}")
            
            # 解析 JSON
            entities = self._extract_json_from_llm_response(content)
            
            if entities and isinstance(entities, dict):
                return entities
            elif entities and isinstance(entities, list) and len(entities) > 0:
                return entities[0]
            else:
                logger.warning("⚠️  LLM 未返回有效的实体")
                return {}
        
        except Exception as e:
            logger.error(f"❌ LLM 实体提取失败: {e}")
            return {}
    
    def _build_candidates_from_ids(
        self,
        matched_ids: List[str],
        table: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        从匹配的 ID 列表构建候选列表
        
        Args:
            matched_ids: 匹配的 ID 列表
            table: 表名
            context: 数据上下文
        
        Returns:
            候选列表，每个候选包含零件的详细信息
        """
        candidates = []
        raw_data = context.get("raw_data") or context
        
        # 根据表名获取数据
        if table == "subgraphs":
            records = raw_data.get("subgraphs", [])
            id_field = "subgraph_id"
        elif table == "features":
            # features 表需要关联 subgraphs 表获取 part_code 和 part_name
            records = raw_data.get("features", [])
            id_field = "feature_id"
            subgraphs = raw_data.get("subgraphs", [])
        elif table == "job_price_snapshots":
            records = raw_data.get("job_price_snapshots", [])
            id_field = "snapshot_id"
        else:
            logger.warning(f"⚠️  不支持的表名: {table}")
            return []
        
        # 构建候选列表
        for record in records:
            if record.get(id_field) in matched_ids:
                # 提取关键信息
                candidate = {
                    "_source": {
                        id_field: record.get(id_field)
                    }
                }
                
                # 根据表类型提取不同的字段
                if table == "features":
                    # features 表：需要从 subgraphs 表获取 part_code 和 part_name
                    subgraph_id = record.get("subgraph_id")
                    subgraph = next((s for s in subgraphs if s.get("subgraph_id") == subgraph_id), None)
                    
                    if subgraph:
                        candidate["part_code"] = subgraph.get("part_code", "N/A")
                        candidate["part_name"] = subgraph.get("part_name", "N/A")
                    else:
                        candidate["part_code"] = "N/A"
                        candidate["part_name"] = "N/A"
                    
                    candidate["material"] = record.get("material", "N/A")
                    candidate["dimensions"] = f"{record.get('length_mm', 0)}×{record.get('width_mm', 0)}×{record.get('thickness_mm', 0)}"
                
                elif table == "subgraphs":
                    # subgraphs 表：直接获取字段
                    candidate["part_code"] = record.get("part_code", "N/A")
                    candidate["part_name"] = record.get("part_name", "N/A")
                    candidate["material"] = record.get("material", "N/A")
                    candidate["dimensions"] = f"{record.get('length_mm', 0)}×{record.get('width_mm', 0)}×{record.get('thickness_mm', 0)}"
                    
                    # 添加额外信息（如果有）
                    if "wire_process_note" in record:
                        candidate["wire_process"] = record.get("wire_process_note", "N/A")
                
                else:
                    # 其他表：基本信息
                    candidate["part_code"] = record.get("part_code", "N/A")
                    candidate["part_name"] = record.get("part_name", "N/A")
                    candidate["material"] = record.get("material", "N/A")
                    candidate["dimensions"] = "N/A"
                
                candidates.append(candidate)
        
        logger.info(f"✅ 构建了 {len(candidates)} 个候选项")
        return candidates
from shared.config import settings
