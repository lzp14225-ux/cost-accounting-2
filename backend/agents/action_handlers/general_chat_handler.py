"""
GeneralChatHandler - 普通聊天处理器
负责人：人员B2

处理普通聊天意图，使用 LLM 生成友好的回复
"""
import os
import logging
from typing import Dict, Any

from .base_handler import BaseActionHandler
from agents.intent_types import IntentResult, ActionResult

logger = logging.getLogger(__name__)


class GeneralChatHandler(BaseActionHandler):
    """
    普通聊天处理器
    
    功能：
    1. 接收用户的普通聊天消息
    2. 构建包含当前数据上下文的 Prompt
    3. 调用 LLM 生成友好的回复
    4. 直接返回结果（不需要确认）
    """
    
    def __init__(self):
        """初始化 Handler"""
        super().__init__()
        
        # LLM 配置
        self.llm_base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
        self.llm_api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.llm_model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT") or settings.LLM_TIMEOUT)
        
        logger.info("✅ GeneralChatHandler 初始化完成")
    
    async def handle(
        self,
        intent_result: IntentResult,
        job_id: str,
        context: Dict[str, Any],
        db_session
    ) -> ActionResult:
        """
        处理普通聊天
        
        Args:
            intent_result: 意图识别结果
            job_id: 任务ID
            context: 当前审核数据上下文
            db_session: 数据库会话
        
        Returns:
            ActionResult: 处理结果
        """
        logger.info(f"💬 处理普通聊天: {intent_result.raw_message}")
        
        try:
            # 1. 构建上下文信息
            context_info = self._build_context_info(context)
            
            # 2. 获取当前时间并构建 Prompt
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            system_prompt = f"""你是一个模具数据审核助手。当前时间：{current_time}

当前审核数据概览：
{context_info}

你的职责：
1. 回答用户关于系统功能的问题
2. 提供操作指导
3. 解释数据含义
4. 提供友好的帮助

重要限制：
- 你只能回答与模具数据核算、审核、修改、价格计算相关的问题
- 对于与核算无关的话题（如闲聊、天气、新闻、其他领域问题等），请礼貌地告知用户："抱歉，我是模具数据核算助手，只能回答与模具核算相关的问题。请问您有什么核算方面的需求吗？"
- 如果用户询问与核算无关的内容，不要回答该问题，而是引导用户回到核算相关的话题

请用简洁、专业的语言回复用户。"""
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": intent_result.raw_message}
            ]
            
            # 3. 调用 LLM
            response = await self._call_llm(messages)
            
            logger.info(f"✅ 聊天回复生成成功")
            
            # 4. 直接返回（不需要确认）
            return ActionResult(
                status="ok",
                message=response if response else "您好！我是模具数据审核助手，可以帮您修改数据、重新识别特征、重新计算价格、查询计算详情等。",
                requires_confirmation=False,
                data={}
            )
        
        except Exception as e:
            logger.error(f"❌ 处理聊天失败: {e}", exc_info=True)
            return ActionResult(
                status="error",
                message=f"抱歉，处理您的消息时出现错误：{str(e)}",
                data={}
            )
    
    def _build_context_info(self, context: Dict[str, Any]) -> str:
        """
        构建上下文信息
        
        Args:
            context: 数据上下文
        
        Returns:
            上下文信息的文本描述
        """
        info_parts = []
        
        # 统计数据
        for table_name, records in context.items():
            if records and isinstance(records, list):
                info_parts.append(f"- {table_name}: {len(records)} 条记录")
        
        # 子图详情（示例）
        if context.get("subgraphs"):
            subgraphs = context["subgraphs"]
            info_parts.append(f"\n子图详情（前3个）：")
            for sg in subgraphs[:3]:
                sg_id = sg.get('subgraph_id', 'N/A')
                part_name = sg.get('part_name', 'N/A')
                material = sg.get('material', 'N/A')
                info_parts.append(f"  - {sg_id} ({part_name}): 材质={material}")
        
        return "\n".join(info_parts) if info_parts else "（当前无数据）"
    
    async def _call_llm(self, messages: list) -> str:
        """
        调用 LLM 生成回复
        
        Args:
            messages: 消息列表
        
        Returns:
            LLM 生成的回复
        """
        try:
            import httpx
            
            # 创建带有自定义 User-Agent 的客户端
            async with httpx.AsyncClient(
                timeout=self.llm_timeout,
                headers={"User-Agent": "curl/8.0"}
            ) as client:
                response = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    json={
                        "model": self.llm_model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 1000
                    },
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json"
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                return result["choices"][0]["message"]["content"]
        
        except Exception as e:
            logger.error(f"❌ LLM 调用失败: {e}")
            return f"抱歉，AI 服务暂时不可用。您可以尝试以下操作：\n1. 修改数据（如：将 UP01 的材质改为 718）\n2. 重新识别特征\n3. 重新计算价格\n4. 查询计算详情"
from shared.config import settings
