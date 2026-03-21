"""
LLM Confirmation Detector - LLM 辅助的确认检测器
负责人：人员B2

职责：
1. 检测用户输入是否是确认性回复（"是的"、"对"、"确认"等）
2. 从聊天历史中提取上下文信息
3. 使用 LLM 理解用户意图并提取实体
"""
import logging
import json
import os
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from shared.config import settings

logger = logging.getLogger(__name__)


class LLMConfirmationDetector:
    """LLM 辅助的确认检测器"""
    
    # 确认性关键词
    CONFIRMATION_KEYWORDS = [
        "是的", "是", "对", "对的", "确认", "好的", "可以", "没错", 
        "正确", "就是", "嗯", "ok", "yes", "y"
    ]
    
    # 拒绝性关键词
    REJECTION_KEYWORDS = [
        "不是", "不对", "错了", "不", "否", "取消", "no", "n"
    ]
    
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
    
    async def detect_confirmation_intent(
        self,
        user_input: str,
        chat_history: List[Dict[str, Any]],
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        检测用户输入是否是确认性回复
        
        Args:
            user_input: 用户输入
            chat_history: 聊天历史
            session_id: 会话ID
        
        Returns:
            如果是确认回复，返回：
            {
                "is_confirmation": True,
                "clarification_id": "...",
                "response_type": "confirm" | "reject",
                "original_clarification": "...",
                "extracted_entities": {...}
            }
            否则返回 None
        """
        logger.info(f"🔍 检测确认意图: {user_input[:50]}...")
        
        # 1. 快速检查：是否包含确认/拒绝关键词
        user_input_lower = user_input.lower().strip()
        
        is_likely_confirmation = any(
            keyword in user_input_lower 
            for keyword in self.CONFIRMATION_KEYWORDS
        )
        
        is_likely_rejection = any(
            keyword in user_input_lower 
            for keyword in self.REJECTION_KEYWORDS
        )
        
        logger.debug(f"  关键词检查: confirmation={is_likely_confirmation}, rejection={is_likely_rejection}")
        
        # 🆕 快速检查：是否包含新请求的特征（查询动作词）
        new_request_keywords = [
            "怎么算", "如何算", "怎么计算", "如何计算",
            "多少钱", "价格", "费用",
            "为什么", "原因",
            "查询", "查看", "显示",
            "是什么", "有哪些"
        ]
        
        is_likely_new_request = any(
            keyword in user_input
            for keyword in new_request_keywords
        )
        
        if is_likely_new_request:
            logger.info(f"❌ 检测到新请求特征（查询动作词），不是确认回复")
            return None
        
        if not (is_likely_confirmation or is_likely_rejection):
            logger.debug(f"❌ 不包含确认/拒绝关键词，跳过")
            return None
        
        logger.info(f"✅ 包含确认/拒绝关键词，继续检测")
        
        # 2. 从聊天历史中查找最近的澄清消息
        clarification_message = self._find_recent_clarification(chat_history)
        
        if not clarification_message:
            logger.warning(f"❌ 未找到最近的澄清消息，跳过")
            return None
        
        logger.info(f"✅ 找到澄清消息: {clarification_message['content'][:100]}...")
        
        # 3. 使用 LLM 理解用户意图
        try:
            llm_result = await self._analyze_with_llm(
                user_input=user_input,
                clarification_message=clarification_message['content'],
                chat_history=chat_history
            )
            
            if llm_result and llm_result.get("is_confirmation_response"):
                logger.info(f"✅ LLM 确认这是确认性回复: {llm_result.get('response_type')}")
                
                # 提取 clarification_id
                clarification_id = clarification_message.get('metadata', {}).get('clarification_id')
                
                logger.info(f"📋 clarification_id: {clarification_id}")
                
                return {
                    "is_confirmation": True,
                    "clarification_id": clarification_id,
                    "response_type": llm_result.get("response_type", "confirm"),
                    "original_clarification": clarification_message['content'],
                    "extracted_entities": llm_result.get("extracted_entities", {}),
                    "confidence": llm_result.get("confidence", 0.9)
                }
            else:
                logger.debug(f"❌ LLM 判断不是确认性回复")
                return None
        
        except Exception as e:
            logger.error(f"❌ LLM 分析失败: {e}", exc_info=True)
            return None
    
    def _find_recent_clarification(
        self,
        chat_history: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        从聊天历史中查找最近的澄清消息
        
        Args:
            chat_history: 聊天历史
        
        Returns:
            最近的澄清消息，如果没有返回 None
        """
        logger.debug(f"🔍 查找澄清消息，历史记录数: {len(chat_history)}")
        
        # 倒序查找（从最新的消息开始）
        for i, message in enumerate(reversed(chat_history)):
            logger.debug(f"  消息 {i}: role={message.get('role')}, metadata={message.get('metadata', {})}")
            
            # 检查是否是助手消息
            if message.get('role') != 'assistant':
                continue
            
            # 检查 metadata 中是否有 clarification_id
            metadata = message.get('metadata', {})
            if metadata.get('action') == 'clarification_request':
                logger.info(f"✅ 找到澄清消息（通过 metadata）: {message.get('content', '')[:100]}")
                return message
            
            # 或者检查消息内容是否包含澄清特征
            content = message.get('content', '')
            if any(keyword in content for keyword in [
                "您是要修改", "请选择", "请指定", "吗？"
            ]):
                logger.info(f"✅ 找到澄清消息（通过内容匹配）: {content[:100]}")
                return message
        
        logger.warning(f"⚠️  未找到澄清消息")
        return None
    
    async def _analyze_with_llm(
        self,
        user_input: str,
        clarification_message: str,
        chat_history: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 分析用户输入是否是确认性回复
        
        Args:
            user_input: 用户输入
            clarification_message: 澄清消息
            chat_history: 聊天历史
        
        Returns:
            LLM 分析结果
        """
        # 构建 prompt
        prompt = f"""你是一个智能助手，负责判断用户的回复是否是对系统澄清问题的确认。

系统刚才发送的澄清消息：
{clarification_message}

用户的回复：
{user_input}

请分析：
1. 用户的回复是否是对澄清消息的确认性回复？
2. 如果是，用户是确认（confirm）还是拒绝（reject）？
3. 从澄清消息中提取关键信息（零件代码、字段、值等）

**重要判断标准：**
- ✅ 确认性回复：用户使用确认词（是的、对、好的、确认等）或直接回答澄清中的问题
- ❌ 新请求：用户提出了完全不同的问题或请求，即使包含零件代码也不算确认
- ❌ 新请求特征：
  * 包含新的动作词（查询、修改、计算等）
  * 提到不同的零件代码
  * 询问"怎么算"、"为什么"、"多少钱"等新问题
  * 话题完全转移

请以 JSON 格式返回：
{{
    "is_confirmation_response": true/false,
    "response_type": "confirm" | "reject" | "unknown",
    "confidence": 0.0-1.0,
    "extracted_entities": {{
        "part_code": "...",
        "field": "...",
        "value": "..."
    }},
    "reasoning": "简短说明判断理由"
}}

示例1：
澄清消息："您是要修改 DIE-01 的工艺代码为【中丝割一修一】吗？"
用户回复："是的"
返回：{{"is_confirmation_response": true, "response_type": "confirm", "confidence": 0.95, "extracted_entities": {{"part_code": "DIE-01", "field": "process_code", "value": "中丝割一修一"}}, "reasoning": "用户明确表示确认"}}

示例2：
澄清消息："您是要修改 DIE-01 的工艺代码为【中丝割一修一】吗？"
用户回复："不是，我要改成慢丝"
返回：{{"is_confirmation_response": true, "response_type": "reject", "confidence": 0.9, "extracted_entities": {{}}, "reasoning": "用户拒绝并提出新的修改"}}

示例3：
澄清消息："您是要修改 DIE-01 的工艺代码为【中丝割一修一】吗？"
用户回复："查询 PU-01 的价格"
返回：{{"is_confirmation_response": false, "response_type": "unknown", "confidence": 0.0, "extracted_entities": {{}}, "reasoning": "用户发起了新的查询，不是对澄清的回复"}}

示例4：
澄清消息："您的输入「5545121」信息不够完整。请提供完整的信息..."
用户回复："DIE-18是怎么算的"
返回：{{"is_confirmation_response": false, "response_type": "unknown", "confidence": 0.0, "extracted_entities": {{}}, "reasoning": "用户提出了新的查询问题（怎么算），不是对澄清的确认，而是一个独立的新请求"}}

示例5：
澄清消息："检测到您想修改 DIE-17 的工艺代码，请选择：1. 慢丝割一修三 2. 慢丝割一修二..."
用户回复："1"
返回：{{"is_confirmation_response": true, "response_type": "confirm", "confidence": 0.95, "extracted_entities": {{"part_code": "DIE-17", "field": "process_code", "value": "慢丝割一修三"}}, "reasoning": "用户选择了第1个选项，是对澄清的确认"}}

现在请分析上面的用户回复。只返回 JSON，不要其他内容。
"""
        
        try:
            # 调用 LLM
            import os
            model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
            
            response = await self.llm_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个专业的意图识别助手，擅长理解用户的确认意图。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # 低温度，更确定性的输出
                max_tokens=500
            )
            
            # 解析响应
            content = response.choices[0].message.content.strip()
            
            # 尝试提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            logger.info(f"✅ LLM 分析结果: {result.get('reasoning')}")
            
            return result
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ LLM 返回的 JSON 解析失败: {e}")
            logger.debug(f"LLM 原始响应: {content}")
            return None
        
        except Exception as e:
            logger.error(f"❌ LLM 调用失败: {e}", exc_info=True)
            return None
    
    async def get_chat_history(
        self,
        session_id: str,
        db: AsyncSession,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取聊天历史
        
        Args:
            session_id: 会话ID
            db: 数据库会话
            limit: 获取最近的 N 条消息
        
        Returns:
            聊天历史列表
        """
        try:
            from api_gateway.repositories.chat_repository import ChatRepository
            
            chat_repo = ChatRepository()
            messages = await chat_repo.get_session_messages(
                db=db,
                session_id=session_id,
                limit=limit
            )
            
            # 转换为标准格式
            history = []
            for msg in messages:
                history.append({
                    "role": msg.role,
                    "content": msg.content,
                    "metadata": msg.metadata or {},
                    "created_at": msg.created_at
                })
            
            return history
        
        except Exception as e:
            logger.error(f"❌ 获取聊天历史失败: {e}", exc_info=True)
            return []
from shared.config import settings
