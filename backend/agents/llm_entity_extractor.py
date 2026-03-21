"""
LLM Entity Extractor - LLM 辅助的实体提取器
负责人：人员B2

职责：
使用 LLM 从用户输入中提取实体信息（零件代码、字段、值等）
"""
import logging
import json
import os
from typing import Dict, Any, Optional
from shared.config import settings

logger = logging.getLogger(__name__)


class LLMEntityExtractor:
    """LLM 辅助的实体提取器"""
    
    def __init__(self):
        self._llm_client = None
    
    @property
    def llm_client(self):
        """懒加载 LLM 客户端"""
        if self._llm_client is None:
            from openai import AsyncOpenAI
            
            # 从环境变量读取配置
            api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
            base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
            
            self._llm_client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url
            )
        return self._llm_client
    
    async def extract_entities(
        self,
        user_input: str,
        available_fields: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        使用 LLM 从用户输入中提取实体
        
        Args:
            user_input: 用户输入
            available_fields: 可用的字段列表（可选）
        
        Returns:
            提取的实体字典：
            {
                "part_code": "DIE-01",
                "field": "process_code",
                "value": "中丝",
                "action": "modify",
                "confidence": 0.95
            }
        """
        logger.info(f"🔍 使用 LLM 提取实体: {user_input[:50]}...")
        
        try:
            # 构建 prompt
            prompt = self._build_extraction_prompt(user_input, available_fields)
            
            # 调用 LLM
            import os
            model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
            
            response = await self.llm_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的实体提取助手，擅长从用户的自然语言输入中提取结构化信息。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # 低温度，更确定性的输出
                max_tokens=500
            )
            
            # 解析响应
            content = response.choices[0].message.content.strip()
            
            # 提取 JSON（支持多种格式）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # 清理可能的注释和多余字符
            lines = content.split('\n')
            cleaned_lines = []
            for line in lines:
                # 移除行尾注释（// 或 #）
                if '//' in line:
                    line = line.split('//')[0]
                if '#' in line and not line.strip().startswith('"'):
                    line = line.split('#')[0]
                cleaned_lines.append(line)
            content = '\n'.join(cleaned_lines).strip()
            
            result = json.loads(content)
            
            logger.info(f"✅ LLM 提取成功: {result}")
            
            return result
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ LLM 返回的 JSON 解析失败: {e}")
            # 尝试记录原始内容以便调试
            try:
                logger.debug(f"LLM 原始响应: {content[:500]}...")  # 只记录前500字符
            except:
                logger.debug("无法记录 LLM 原始响应")
            # 返回空实体
            return {}
        
        except Exception as e:
            logger.error(f"❌ LLM 实体提取失败: {e}", exc_info=True)
            # 返回空实体
            return {}
    
    def _build_extraction_prompt(
        self,
        user_input: str,
        available_fields: Optional[list] = None
    ) -> str:
        """
        构建实体提取的 prompt
        
        Args:
            user_input: 用户输入
            available_fields: 可用的字段列表
        
        Returns:
            prompt 字符串
        """
        prompt = f"""你是一个模具制造领域的实体提取专家。请从用户的输入中提取以下信息：

用户输入：
{user_input}

🔴 **最重要的规则（必须首先检查）**：
1. 如果输入包含"按重量计算"、"重量计算"、"按重量" → 返回 `action: "weight_price_calculation"`
2. 如果输入包含"重新识别"、"识别特征"、"跑特征" → 返回 `action: "feature_recognition"`
3. 如果输入包含"重新计算"、"重算"、"计算价格" → 返回 `action: "price_calculation"`
4. 如果输入包含"怎么算"、"为什么"、"详情"、"对吗" → 返回 `action: "query"`
5. 如果输入包含"全部"、"所有"、"全体"、"整体"、"批量" + 修改动词 → `part_code: null`, `action: "data_modification"`
6. 只有明确的字段修改（如"改为"、"设置为"、"修改"）才返回 `action: "data_modification"`

请提取：
1. **零件代码** (part_code): 如 DIE-01, PU-01, BL-01 等
   - 🆕 如果用户说"XX开头"、"以XX开头"、"XX开头的" → 返回 `part_code_prefix: "XX"`
   - 🆕 如果用户说"XX结尾"、"以XX结尾"、"XX结尾的" → 返回 `part_code_suffix: "XX"`
   - 🆕 如果用户说"包含XX"、"含有XX" → 返回 `part_code_contains: "XX"`
2. **字段名** (field): 用户想要修改的字段
   - process_code: 工艺代码（如：慢丝、中丝、快丝、线割等）
   - material: 材质（如：CR12, SKD11, 718 等）
   - length_mm: 长度
   - width_mm: 宽度
   - thickness_mm: 厚度
   - quantity: 数量
   - weight: 重量
3. **值** (value): 新的值（可能是简略形式）
4. **动作** (action): 用户的意图
   - data_modification: 修改字段值（必须有明确的修改动词）
   - query: 查询信息
   - weight_price_calculation: 按重量计算价格（特殊操作）
   - feature_recognition: 重新识别特征（特殊操作）
   - price_calculation: 重新计算价格（特殊操作）

🔴 **批量操作识别**：
- 如果输入包含"全部"、"所有"、"全体"、"整体"、"批量"等关键词
- 且是修改操作（有"改为"、"修改"等动词）
- 则 part_code 应为 null，但 action 仍为 "data_modification"
- reasoning 中必须明确说明"批量操作"或包含批量关键词

请以 JSON 格式返回：
{{
    "part_code": "零件代码或null",
    "part_code_prefix": "前缀或null（如用户说'B2开头'则为'B2'）",
    "part_code_suffix": "后缀或null（如用户说'01结尾'则为'01'）",
    "part_code_contains": "包含字符串或null（如用户说'包含DIE'则为'DIE'）",
    "field": "字段名或null",
    "value": "值或null",
    "action": "动作",
    "confidence": 0.0-1.0,
    "reasoning": "简短说明提取理由"
}}

🔴 **特殊操作示例（优先匹配）**：

示例A：
输入："DIE-10按重量计算"
返回：{{"part_code": "DIE-10", "field": null, "value": null, "action": "weight_price_calculation", "confidence": 0.95, "reasoning": "包含'按重量计算'关键词，是特殊操作"}}

示例B：
输入："重新识别 UP-01"
返回：{{"part_code": "UP-01", "field": null, "value": null, "action": "feature_recognition", "confidence": 0.95, "reasoning": "包含'重新识别'关键词，是特殊操作"}}

示例C：
输入："重新计算 DIE-03 的价格"
返回：{{"part_code": "DIE-03", "field": null, "value": null, "action": "price_calculation", "confidence": 0.95, "reasoning": "包含'重新计算'关键词，是特殊操作"}}

示例D：
输入："DIE-18是怎么算的"
返回：{{"part_code": "DIE-18", "field": null, "value": null, "action": "query", "confidence": 0.95, "reasoning": "包含'怎么算'查询词，是查询操作"}}

**批量操作示例（重要）**：

示例E：
输入："全部工艺改为中丝割一修一"
返回：{{"part_code": null, "part_code_prefix": null, "part_code_suffix": null, "part_code_contains": null, "field": "process_code", "value": "中丝割一修一", "action": "data_modification", "confidence": 0.95, "reasoning": "用户明确指定「全部」零件的工艺代码修改为「中丝割一修一」，这是批量操作"}}

示例F：
输入："所有零件材质改为718"
返回：{{"part_code": null, "part_code_prefix": null, "part_code_suffix": null, "part_code_contains": null, "field": "material", "value": "718", "action": "data_modification", "confidence": 0.95, "reasoning": "用户明确指定「所有」零件的材质修改为「718」，这是批量操作"}}

示例G：
输入："把全体的长度改成100"
返回：{{"part_code": null, "part_code_prefix": null, "part_code_suffix": null, "part_code_contains": null, "field": "length_mm", "value": "100", "action": "data_modification", "confidence": 0.9, "reasoning": "用户使用「全体」关键词，表示批量修改所有零件的长度"}}

**🆕 前缀/后缀/包含匹配示例（重要）**：

示例H：
输入："B2开头的材质改为Cr12mov"
返回：{{"part_code": null, "part_code_prefix": "B2", "part_code_suffix": null, "part_code_contains": null, "field": "material", "value": "Cr12mov", "action": "data_modification", "confidence": 0.95, "reasoning": "用户指定「B2开头」的零件，这是前缀匹配模式"}}

示例I：
输入："以UP开头的零件工艺改为慢丝"
返回：{{"part_code": null, "part_code_prefix": "UP", "part_code_suffix": null, "part_code_contains": null, "field": "process_code", "value": "慢丝", "action": "data_modification", "confidence": 0.95, "reasoning": "用户指定「以UP开头」的零件，这是前缀匹配模式"}}

示例J：
输入："01结尾的零件材质改为718"
返回：{{"part_code": null, "part_code_prefix": null, "part_code_suffix": "01", "part_code_contains": null, "field": "material", "value": "718", "action": "data_modification", "confidence": 0.95, "reasoning": "用户指定「01结尾」的零件，这是后缀匹配模式"}}

示例K：
输入："包含DIE的零件改为快丝"
返回：{{"part_code": null, "part_code_prefix": null, "part_code_suffix": null, "part_code_contains": "DIE", "field": "process_code", "value": "快丝", "action": "data_modification", "confidence": 0.95, "reasoning": "用户指定「包含DIE」的零件，这是包含匹配模式"}}

**普通修改示例**：

示例1：
输入："Die-01用中丝"
返回：{{"part_code": "DIE-01", "field": "process_code", "value": "中丝", "action": "data_modification", "confidence": 0.9, "reasoning": "用户想修改DIE-01的工艺为中丝"}}

示例2：
输入："修改 PU-01 的材质为 718"
返回：{{"part_code": "PU-01", "field": "material", "value": "718", "action": "data_modification", "confidence": 0.95, "reasoning": "明确的修改指令"}}

示例3：
输入："查询 BL-01 的价格"
返回：{{"part_code": "BL-01", "field": "price", "value": null, "action": "query", "confidence": 0.9, "reasoning": "查询价格信息"}}

示例4：
输入："Die-02改成慢丝割一修三"
返回：{{"part_code": "DIE-02", "field": "process_code", "value": "慢丝割一修三", "action": "data_modification", "confidence": 0.95, "reasoning": "修改工艺为完整名称"}}

示例5：
输入："把上模仁的长度改成100"
返回：{{"part_code": null, "field": "length_mm", "value": "100", "action": "data_modification", "confidence": 0.7, "reasoning": "缺少明确的零件代码，只有描述性名称"}}

注意事项：
1. **优先检查特殊操作关键词**（按重量计算、重新识别、重新计算、怎么算）
2. **检查批量操作关键词**（全部、所有、全体、整体、批量）→ part_code=null 但 action="data_modification"
3. **🆕 检查前缀/后缀/包含模式**：
   - "XX开头"、"以XX开头" → part_code_prefix="XX"
   - "XX结尾"、"以XX结尾" → part_code_suffix="XX"
   - "包含XX"、"含有XX" → part_code_contains="XX"
4. 零件代码通常是大写字母+数字的组合（如 DIE-01, PU-01）
5. 工艺相关的关键词：慢丝、中丝、快丝、线割、割一修一、割一修二、割一修三、割一刀
6. 如果用户使用简略形式（如"中丝"），保留原始输入，不要自动补全
7. 如果信息不明确，confidence 应该较低
8. 如果完全无法提取某个字段，返回 null
9. **批量操作的 reasoning 必须包含批量关键词**（如"全部"、"所有"等）
10. **🆕 前缀/后缀/包含模式的 reasoning 必须说明匹配模式**（如"前缀匹配"、"后缀匹配"、"包含匹配"）

现在请分析上面的用户输入。只返回 JSON，不要其他内容。
"""
        
        # 如果提供了可用字段列表，添加到 prompt
        if available_fields:
            prompt += f"\n\n可用的字段列表：\n{', '.join(available_fields)}"
        
        return prompt
from shared.config import settings
