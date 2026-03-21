"""
WeightPriceQueryHandler - 查询按重量计算详情处理器
负责人：人员B2

处理查询按重量计算详情的意图，从数据库查询并格式化 weight_price_steps
"""
import logging
import json
import os
from typing import Dict, Any, Optional, List
from sqlalchemy import select
import httpx

from .base_handler import BaseActionHandler
from agents.intent_types import IntentResult, ActionResult

logger = logging.getLogger(__name__)


class WeightPriceQueryHandler(BaseActionHandler):
    """
    查询按重量计算详情处理器
    
    功能：
    1. 从意图中提取 subgraph_id
    2. 查询 processing_cost_calculation_details 表的 weight_price_steps 字段
    3. 使用 LLM 格式化 weight_price_steps JSON 为友好的文本
    4. 直接返回结果（不需要确认）
    """
    
    def __init__(self):
        """初始化 Handler"""
        super().__init__()
        
        # LLM 配置
        self.use_llm = os.getenv("USE_LLM_FOR_WEIGHT_PRICE_QUERY", "true").lower() == "true"
        self.llm_base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
        self.llm_api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.llm_model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT") or settings.LLM_TIMEOUT)
        
        # 历史消息配置
        self.use_chat_history = os.getenv("USE_CHAT_HISTORY", "true").lower() == "true"
        self.max_history_messages = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))
        
        # HTTP 客户端
        self.http_client = httpx.AsyncClient(
            timeout=self.llm_timeout,
            headers={
                "User-Agent": "curl/8.0"
            }
        )
        
        # 懒加载 ChatHistoryRepository
        self._chat_history_repo = None
        
        logger.info(f"✅ WeightPriceQueryHandler 初始化完成 (use_llm={self.use_llm}, use_chat_history={self.use_chat_history})")
    
    @property
    def chat_history_repo(self):
        """懒加载 ChatHistoryRepository"""
        if self._chat_history_repo is None:
            from api_gateway.repositories.chat_history_repository import ChatHistoryRepository
            self._chat_history_repo = ChatHistoryRepository()
        return self._chat_history_repo
    
    async def handle(
        self,
        intent_result: IntentResult,
        job_id: str,
        context: Dict[str, Any],
        db_session
    ) -> ActionResult:
        """
        处理查询按重量计算详情请求
        
        Args:
            intent_result: 意图识别结果
            job_id: 任务ID
            context: 当前审核数据上下文
            db_session: 数据库会话
        
        Returns:
            ActionResult: 处理结果
        """
        logger.info(f"🔍 处理查询按重量计算详情: {intent_result.raw_message}")
        logger.info(f"📋 接收参数: subgraph_id={intent_result.parameters.get('subgraph_id')}")
        
        try:
            # 1. 提取 subgraph_id
            subgraph_id = intent_result.parameters.get("subgraph_id")
            
            # 如果 subgraph_id 为空，尝试从历史消息中推断
            if not subgraph_id and self.use_chat_history:
                logger.info(f"🔍 subgraph_id 为空，尝试从历史消息推断...")
                subgraph_id = await self._infer_subgraph_from_history(db_session, job_id)
                
                if subgraph_id:
                    logger.info(f"✅ 从历史推断出 subgraph_id: {subgraph_id}")
                else:
                    logger.warning(f"⚠️  无法从历史推断 subgraph_id")
            elif subgraph_id and self.use_chat_history:
                # 双重验证：检查 LLM 提取的 subgraph_id 是否是最近提到的
                if intent_result.raw_message and any(pronoun in intent_result.raw_message for pronoun in ["它", "那个", "这个", "那", "这"]):
                    logger.info(f"🔍 检测到代词，验证 LLM 推断的 subgraph_id: {subgraph_id}")
                    verified_id = await self._infer_subgraph_from_history(db_session, job_id)
                    
                    if verified_id and verified_id != subgraph_id:
                        logger.warning(f"⚠️  LLM 推断的 {subgraph_id} 与历史推断的 {verified_id} 不一致，使用历史推断结果")
                        subgraph_id = verified_id
                    else:
                        logger.info(f"✅ LLM 推断验证通过: {subgraph_id}")
            
            if not subgraph_id:
                return ActionResult(
                    status="error",
                    message="请指定要查询的子图，例如：'UP01 按重量怎么算的？'",
                    requires_confirmation=False,
                    data={}
                )
            
            # 2. 查询数据库
            detail = await self._query_weight_price_detail(
                db_session,
                job_id,
                subgraph_id
            )
            
            if not detail:
                return ActionResult(
                    status="ok",
                    message=f"{subgraph_id} 未查询到该零件。",
                    requires_confirmation=False,
                    data={}
                )
            
            # 3. 检查 weight_price_steps 字段
            weight_price_steps = getattr(detail, 'weight_price_steps', None)
            logger.info(f"📊 weight_price_steps 类型: {type(weight_price_steps)}, 值: {weight_price_steps is not None}")
            
            if not weight_price_steps:
                logger.warning(f"⚠️  weight_price_steps 为空或 None")
                return ActionResult(
                    status="ok",
                    message=f"{subgraph_id} 暂无按重量计算的详情数据。",
                    requires_confirmation=False,
                    data={}
                )
            
            # 🆕 3.5. 处理嵌套结构
            # 实际数据格式: [{"steps": [...], "category": "weight_price"}]
            # 需要提取 steps 数组
            logger.info(f"📊 处理前 - weight_price_steps 类型: {type(weight_price_steps)}")
            if isinstance(weight_price_steps, list):
                logger.info(f"📊 weight_price_steps 是列表，长度: {len(weight_price_steps)}")
                if len(weight_price_steps) > 0:
                    first_item = weight_price_steps[0]
                    logger.info(f"📊 第一个元素类型: {type(first_item)}, 是字典: {isinstance(first_item, dict)}")
                    if isinstance(first_item, dict):
                        logger.info(f"📊 第一个元素的键: {first_item.keys()}")
                        if "steps" in first_item:
                            # 提取嵌套的 steps 数组
                            weight_price_steps = first_item["steps"]
                            logger.info(f"✅ 提取嵌套的 steps 数组，共 {len(weight_price_steps)} 个步骤")
                        else:
                            logger.info(f"📊 第一个元素没有 'steps' 键")
            
            # 验证是否有有效数据
            logger.info(f"📊 验证 - weight_price_steps 类型: {type(weight_price_steps)}, 是列表: {isinstance(weight_price_steps, list)}")
            if isinstance(weight_price_steps, list):
                logger.info(f"📊 验证 - 列表长度: {len(weight_price_steps)}")
            
            if not weight_price_steps or (isinstance(weight_price_steps, list) and len(weight_price_steps) == 0):
                logger.warning(f"⚠️  weight_price_steps 验证失败：为空或长度为0")
                return ActionResult(
                    status="ok",
                    message=f"{subgraph_id} 暂无按重量计算的详情数据。",
                    requires_confirmation=False,
                    data={}
                )
            
            # 4. 格式化 weight_price_steps
            if self.use_llm:
                try:
                    formatted_message = await self._format_with_llm(
                        job_id,
                        subgraph_id,
                        weight_price_steps,
                        intent_result.raw_message,
                        db_session
                    )
                    logger.info(f"✅ LLM 格式化成功: {subgraph_id}")
                except Exception as e:
                    logger.error(f"❌ LLM 格式化失败: {e}，降级到规则格式化")
                    formatted_message = self._format_weight_price_steps(
                        subgraph_id,
                        weight_price_steps
                    )
            else:
                formatted_message = self._format_weight_price_steps(
                    subgraph_id,
                    weight_price_steps
                )
                logger.info(f"✅ 规则格式化完成: {subgraph_id}")
            
            # 5. 直接返回（不需要确认）
            return ActionResult(
                status="ok",
                message=formatted_message,
                requires_confirmation=False,
                data={
                    "subgraph_id": subgraph_id,
                    "weight_price_steps": weight_price_steps
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 查询按重量计算详情失败: {e}", exc_info=True)
            return ActionResult(
                status="error",
                message=f"查询按重量计算详情失败：{str(e)}",
                data={}
            )
    
    async def _query_weight_price_detail(
        self,
        db_session,
        job_id: str,
        subgraph_id: str
    ):
        """
        查询按重量计算详情（支持模糊匹配）
        
        Args:
            db_session: 数据库会话
            job_id: 任务ID
            subgraph_id: 子图ID（支持短名称，如 "UP-01"）
        
        Returns:
            ProcessingCostCalculationDetail 或 None
        """
        try:
            from shared.models import ProcessingCostCalculationDetail
            
            # 1. 先尝试精确匹配
            result = await db_session.execute(
                select(ProcessingCostCalculationDetail)
                .where(
                    ProcessingCostCalculationDetail.subgraph_id == subgraph_id,
                    ProcessingCostCalculationDetail.job_id == job_id
                )
            )
            
            detail = result.scalar_one_or_none()
            
            # 2. 如果精确匹配失败，尝试后缀匹配（支持 UUID_短名称 格式）
            if not detail:
                logger.info(f"🔍 精确匹配失败，尝试后缀匹配: {subgraph_id}")
                result = await db_session.execute(
                    select(ProcessingCostCalculationDetail)
                    .where(
                        ProcessingCostCalculationDetail.subgraph_id.like(f'%_{subgraph_id}'),
                        ProcessingCostCalculationDetail.job_id == job_id
                    )
                )
                
                all_matches = result.scalars().all()
                
                if len(all_matches) == 0:
                    logger.warning(f"⚠️  未找到匹配的子图: {subgraph_id}")
                    detail = None
                elif len(all_matches) == 1:
                    detail = all_matches[0]
                    logger.info(f"✅ 后缀匹配成功: {detail.subgraph_id}")
                else:
                    # 多个匹配结果，选择最短的（最可能是正确的）
                    detail = min(all_matches, key=lambda x: len(x.subgraph_id))
                    logger.warning(f"⚠️  找到 {len(all_matches)} 个匹配结果，选择最短的: {detail.subgraph_id}")
                    logger.debug(f"   所有匹配: {[m.subgraph_id for m in all_matches]}")
            
            return detail
        
        except Exception as e:
            logger.error(f"❌ 数据库查询失败: {e}", exc_info=True)
            return None
    
    async def _format_with_llm(
        self,
        job_id: str,
        subgraph_id: str,
        weight_price_steps: Any,
        user_question: str,
        db_session
    ) -> str:
        """
        使用 LLM 格式化按重量计算步骤（支持历史对话上下文）
        
        Args:
            job_id: 任务ID（用于查询历史消息）
            subgraph_id: 子图ID
            weight_price_steps: 按重量计算步骤 JSON
            user_question: 用户的原始问题
            db_session: 数据库会话（用于查询历史）
        
        Returns:
            LLM 生成的友好回答
        """
        logger.info(f"🤖 使用 LLM 格式化按重量计算详情: {subgraph_id}")
        
        # 解析 JSON（如果是字符串）
        if isinstance(weight_price_steps, str):
            steps = json.loads(weight_price_steps)
        else:
            steps = weight_price_steps
        
        # 🆕 处理嵌套结构：如果是 [{"steps": [...], "category": "..."}] 格式
        if isinstance(steps, list) and len(steps) > 0:
            first_item = steps[0]
            if isinstance(first_item, dict) and "steps" in first_item:
                steps = first_item["steps"]
                logger.info(f"✅ LLM格式化：提取嵌套的 steps 数组")
        
        # 构建 Prompt
        prompt = f"""你是一个模具成本计算专家。用户询问了以下问题：

"{user_question}"

以下是 {subgraph_id} 的按重量计算详情数据（JSON格式）：

```json
{json.dumps(steps, ensure_ascii=False, indent=2)}
```

## 字段说明

### 步骤 1: 获取零件信息
- `length_mm`: 长度（毫米）
- `width_mm`: 宽度（毫米）
- `thickness_mm`: 厚度（毫米）
- `material`: 材料名称

### 步骤 2: 匹配材料密度
- `material`: 原始材料名称
- `matched_sub_category`: 匹配到的材料子类别
- `density`: 密度值（g/cm³）
- `unit`: 密度单位

### 步骤 3: 计算重量
- `formula`: 计算公式
- `weight`: 计算得到的重量（千克）
- `unit`: 重量单位

**计算公式**: `weight(kg) = length_mm × width_mm × thickness_mm × density`

### 步骤 4: 匹配重量规则
- `weight`: 重量（千克）
- `matched_range`: 匹配到的重量范围（如 "[0.001, 499.999]"）
- `rule_price`: 规则价格系数（元/kg）
- `sub_category`: 规则子类别

**规则说明**: 根据重量范围匹配不同的价格系数，重量越大，单价越低。

### 步骤 5: 计算加权价格
- `formula`: 计算公式
- `weight_price`: 最终的按重量计算价格（元）
- `unit`: 价格单位

**计算公式**: `weight_price = weight × rule_price`

---

请根据用户的问题，用友好、易懂的语言解释计算过程。要求：

1. **针对性回答**：重点回答用户关心的部分
2. **结构清晰**：使用分点、分段，便于阅读
3. **通俗易懂**：避免技术术语，用口语化表达
4. **包含数据**：引用具体的数值和公式
5. **使用实际字段**：只使用 JSON 数据中实际存在的字段名和值
6. **结束方式**：回答完成后，以一句话总结即可，不要提供额外的建议或询问

请开始回答："""

        # 构建消息数组（包含历史对话）
        messages = [
            {
                "role": "system",
                "content": "你是一个模具成本计算专家，擅长用通俗易懂的语言解释按重量计算的过程。你的回答要专业、准确、简洁。"
            }
        ]
        
        # 如果启用了历史记忆，加载历史消息
        if self.use_chat_history and db_session:
            try:
                history_messages = await self._load_chat_history(db_session, job_id)
                messages.extend(history_messages)
                logger.info(f"✅ 加载了 {len(history_messages)} 条历史消息")
            except Exception as e:
                logger.warning(f"⚠️  加载历史消息失败: {e}，继续使用无历史模式")
        
        # 添加当前问题
        messages.append({
            "role": "user",
            "content": prompt
        })

        # 调用 LLM
        try:
            response = await self.http_client.post(
                f"{self.llm_base_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2000
                },
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            llm_response = result["choices"][0]["message"]["content"]
            logger.info(f"✅ LLM 格式化成功，响应长度: {len(llm_response)}")
            
            return llm_response
        
        except httpx.TimeoutException as e:
            logger.error(f"❌ LLM API 请求超时: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ LLM API 返回错误状态: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"❌ LLM 格式化异常: {e}", exc_info=True)
            raise
    
    async def _load_chat_history(
        self,
        db_session,
        job_id: str
    ) -> List[Dict[str, str]]:
        """
        加载聊天历史（用于LLM上下文）
        
        Args:
            db_session: 数据库会话
            job_id: 任务ID（作为 session_id）
        
        Returns:
            消息列表，格式: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        try:
            # 查询最近的历史消息
            history = await self.chat_history_repo.get_session_history(
                db_session,
                session_id=job_id,
                limit=self.max_history_messages
            )
            
            if not history:
                logger.debug(f"📭 没有找到历史消息: job_id={job_id}")
                return []
            
            # 转换为 LLM 消息格式
            messages = []
            for msg in history:
                role = msg["role"]
                content = msg["content"]
                
                # 只保留 user 和 assistant 消息（跳过 system）
                if role in ["user", "assistant"]:
                    messages.append({
                        "role": role,
                        "content": content
                    })
            
            logger.info(f"📚 加载历史消息: job_id={job_id}, 总数={len(history)}, 有效消息={len(messages)}")
            
            return messages
        
        except Exception as e:
            logger.error(f"❌ 加载历史消息失败: {e}", exc_info=True)
            return []
    
    async def _infer_subgraph_from_history(
        self,
        db_session,
        job_id: str
    ) -> Optional[str]:
        """
        从历史消息中推断 subgraph_id
        
        当用户使用代词（如"那"、"它"、"这个"）时，从最近的历史消息中查找提到的子图ID
        
        Args:
            db_session: 数据库会话
            job_id: 任务ID
        
        Returns:
            推断出的 subgraph_id，如果无法推断返回 None
        """
        try:
            logger.info(f"📚 开始从历史推断子图ID: job_id={job_id}")
            
            # 查询最近的历史消息
            history = await self.chat_history_repo.get_recent_session_history(
                db_session,
                session_id=job_id,
                limit=50
            )
            
            logger.info(f"📊 查询到 {len(history)} 条历史消息")
            
            if not history:
                logger.warning(f"📭 没有历史消息")
                return None
            
            import re
            
            # 子图ID模式（与 QueryDetailsHandler 相同）
            subgraph_prefixes = r'(?:' + '|'.join([
                r'UP_JIAT', r'PS_JIAT', r'LOW_JIAT',
                r'UP_ITEM', r'PSITEM', r'LOW_ITEM',
                r'DIE2_P', r'PS2_P', r'PPS2_P', r'PH2_P', r'LB2_P',
                r'UP_P', r'UB_P', r'PH_P', r'PU_P', r'PPS_P', r'PS_P', r'DIE_P', r'GU_P', r'LB_P',
                r'TEMP[12]', r'ST[123]',
                r'DIE2', r'PS2', r'PPS2', r'PH2', r'LB2',
                r'STRIP',
                r'PPS', r'DIE', r'CAM', r'BOL',
                r'UP', r'LP', r'PS', r'PH', r'UB', r'PU', r'LB', r'EB', r'EJ', 
                r'CV', r'CJ', r'CB', r'GU', r'RP', r'CP', r'TP', r'BP', r'SP', r'MP', r'PP',
                r'U[12]', r'B[12]',
            ]) + r')'
            
            subgraph_pattern = rf'({subgraph_prefixes}[-_]?(?:\d{{2}}|[A-Z]+\d+))'
            
            # 优先级 1：从最近的用户消息中查找
            user_messages = [msg for msg in reversed(history) if msg.get("role") == "user"]
            logger.info(f"🔍 找到 {len(user_messages)} 条用户消息")
            
            for i, msg in enumerate(user_messages[:3]):
                content = msg.get("content", "")
                logger.info(f"  🔍 [{i}] 尝试匹配用户消息: {content[:100]}")
                matches = re.findall(subgraph_pattern, content, re.IGNORECASE)
                
                if matches:
                    subgraph_id = matches[0].upper()
                    logger.info(f"✅ 从最近的用户消息推断出子图: {subgraph_id} (第{i}条)")
                    return subgraph_id
            
            # 优先级 2：从最近的助手消息中查找
            assistant_messages = [msg for msg in reversed(history) if msg.get("role") == "assistant"]
            logger.info(f"🔍 找到 {len(assistant_messages)} 条助手消息")
            for msg in assistant_messages[:5]:
                content = msg.get("content", "")
                matches = re.findall(subgraph_pattern, content, re.IGNORECASE)
                
                if matches:
                    subgraph_id = matches[0].upper()
                    logger.info(f"✅ 从最近的助手消息推断出子图: {subgraph_id}")
                    return subgraph_id
            
            # 优先级 3：从所有消息中查找
            for msg in reversed(history):
                content = msg.get("content", "")
                matches = re.findall(subgraph_pattern, content, re.IGNORECASE)
                
                if matches:
                    subgraph_id = matches[0].upper()
                    logger.info(f"✅ 从历史消息推断出子图: {subgraph_id}")
                    return subgraph_id
            
            logger.warning(f"⚠️  历史消息中未找到子图ID")
            return None
        
        except Exception as e:
            logger.error(f"❌ 推断子图ID失败: {e}", exc_info=True)
            return None
    
    def _format_weight_price_steps(
        self,
        subgraph_id: str,
        weight_price_steps: Any
    ) -> str:
        """
        使用规则格式化按重量计算步骤
        
        Args:
            subgraph_id: 子图ID
            weight_price_steps: 按重量计算步骤 JSON
        
        Returns:
            格式化后的文本
        """
        # 解析 JSON（如果是字符串）
        if isinstance(weight_price_steps, str):
            steps = json.loads(weight_price_steps)
        else:
            steps = weight_price_steps
        
        logger.debug(f"🔍 格式化前 - steps类型: {type(steps)}, 长度: {len(steps) if isinstance(steps, list) else 'N/A'}")
        if isinstance(steps, list) and len(steps) > 0:
            logger.debug(f"🔍 第一个元素类型: {type(steps[0])}, 键: {steps[0].keys() if isinstance(steps[0], dict) else 'N/A'}")
        
        # 🆕 处理嵌套结构：如果是 [{"steps": [...], "category": "..."}] 格式
        if isinstance(steps, list) and len(steps) > 0:
            first_item = steps[0]
            if isinstance(first_item, dict) and "steps" in first_item:
                steps = first_item["steps"]
                logger.info(f"✅ 规则格式化：提取嵌套的 steps 数组，共 {len(steps)} 个步骤")
        
        logger.debug(f"🔍 格式化后 - steps类型: {type(steps)}, 长度: {len(steps) if isinstance(steps, list) else 'N/A'}")
        if isinstance(steps, list) and len(steps) > 0:
            logger.debug(f"🔍 第一个元素类型: {type(steps[0])}, 键: {steps[0].keys() if isinstance(steps[0], dict) else 'N/A'}")
        
        # 验证 steps 是否为有效的步骤数组
        if not isinstance(steps, list) or len(steps) == 0:
            logger.warning(f"⚠️  steps 不是有效的数组: type={type(steps)}, len={len(steps) if isinstance(steps, list) else 'N/A'}")
            return f"📊 {subgraph_id} 的按重量计算详情：\n\n数据格式错误，无法解析。"
        
        # 构建输出
        lines = [f"📊 {subgraph_id} 的按重量计算详情：\n"]
        
        for i, step in enumerate(steps, 1):
            step_name = step.get("step", f"步骤 {i}")
            lines.append(f"**{i}. {step_name}**")
            
            # 根据步骤类型格式化
            if "获取零件信息" in step_name:
                lines.append(f"  - 长度: {step.get('length_mm')} mm")
                lines.append(f"  - 宽度: {step.get('width_mm')} mm")
                lines.append(f"  - 厚度: {step.get('thickness_mm')} mm")
                lines.append(f"  - 材料: {step.get('material')}")
            
            elif "匹配材料密度" in step_name:
                lines.append(f"  - 材料: {step.get('material')}")
                lines.append(f"  - 匹配到: {step.get('matched_sub_category')}")
                lines.append(f"  - 密度: {step.get('density')} {step.get('unit', 'g/cm³')}")
            
            elif "计算重量" in step_name:
                lines.append(f"  - 公式: {step.get('formula')}")
                lines.append(f"  - 重量: {step.get('weight')} {step.get('unit', 'kg')}")
            
            elif "匹配重量规则" in step_name:
                lines.append(f"  - 重量: {step.get('weight')} kg")
                lines.append(f"  - 匹配范围: {step.get('matched_range')}")
                lines.append(f"  - 规则价格: {step.get('rule_price')} 元/kg")
            
            elif "计算加权价格" in step_name:
                lines.append(f"  - 公式: {step.get('formula')}")
                lines.append(f"  - 最终价格: {step.get('weight_price')} {step.get('unit', '元')}")
            
            else:
                # 通用格式化
                for key, value in step.items():
                    if key != "step":
                        lines.append(f"  - {key}: {value}")
            
            lines.append("")  # 空行
        
        return "\n".join(lines)
from shared.config import settings
