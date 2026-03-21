"""
ConfirmationResponseHandler - 确认响应处理器
负责人：人员B2

职责：
1. 处理用户的确认响应（如 "1", "1-5", "全部"）
2. 调用 ConfirmationHandler 解析用户选择
3. 应用操作到选中的零件
"""
import logging
from typing import Dict, Any

from .base_handler import BaseActionHandler
from agents.intent_types import IntentResult, ActionResult

logger = logging.getLogger(__name__)


class ConfirmationResponseHandler(BaseActionHandler):
    """确认响应处理器"""
    
    def __init__(self):
        """初始化确认响应处理器"""
        super().__init__()
        self._confirmation_handler = None
        logger.info("✅ ConfirmationResponseHandler 初始化完成")
    
    @property
    def confirmation_handler(self):
        """懒加载 ConfirmationHandler"""
        if self._confirmation_handler is None:
            from .confirmation_handler import ConfirmationHandler
            self._confirmation_handler = ConfirmationHandler()
        return self._confirmation_handler
    
    async def handle(
        self,
        intent_result: IntentResult,
        job_id: str,
        context: Dict[str, Any],
        db_session
    ) -> ActionResult:
        """
        处理确认响应
        
        流程：
        1. 从 intent_result.parameters 中获取用户选择
        2. 调用 ConfirmationHandler.handle_confirmation_response()
        3. 如果用户取消，返回取消结果
        4. 如果用户确认，应用操作到选中的零件
        
        Args:
            intent_result: 意图识别结果
            job_id: 任务ID
            context: 数据上下文
            db_session: 数据库会话
        
        Returns:
            ActionResult: 处理结果
        """
        logger.info(f"🔧 处理确认响应: job_id={job_id}")
        
        try:
            # 1. 获取用户选择
            user_selection = intent_result.parameters.get("user_selection", "")
            logger.info(f"📝 用户选择: '{user_selection}'")
            
            # 2. 调用 ConfirmationHandler 处理
            confirmation_result = await self.confirmation_handler.handle_confirmation_response(
                job_id,
                user_selection,
                db_session
            )
            
            # 3. 检查结果
            if confirmation_result.status == "cancelled":
                logger.info(f"❌ 用户取消操作")
                return ActionResult(
                    status="ok",
                    message=confirmation_result.message,
                    requires_confirmation=False,
                    data={}
                )
            
            if confirmation_result.status == "error":
                logger.error(f"❌ 确认处理失败: {confirmation_result.message}")
                return ActionResult(
                    status="error",
                    message=confirmation_result.message,
                    requires_confirmation=False,
                    data={}
                )
            
            # 4. 用户确认，应用操作
            logger.info(f"✅ 用户确认，开始应用操作...")
            
            selected_candidates = confirmation_result.data.get("selected_candidates", [])
            original_message = confirmation_result.data.get("original_message", "")
            parsed_intent = confirmation_result.data.get("parsed_intent", {})
            
            logger.info(f"📊 选中 {len(selected_candidates)} 个零件")
            logger.info(f"📝 原始消息: {original_message}")
            logger.info(f"🔍 原始意图: {parsed_intent.get('intent_type')}")
            
            # 5. 根据原始意图类型，调用对应的 Handler
            original_intent_type = parsed_intent.get("intent_type")
            
            if not original_intent_type:
                logger.error(f"❌ 原始意图类型为空")
                return ActionResult(
                    status="error",
                    message="确认上下文损坏，缺少原始意图类型",
                    requires_confirmation=False,
                    data={}
                )
            
            # 6. 获取原始 Handler
            from .base_handler import ActionHandlerFactory
            
            original_handler = ActionHandlerFactory.get_handler(original_intent_type)
            
            if not original_handler:
                logger.error(f"❌ 未找到原始 Handler: {original_intent_type}")
                return ActionResult(
                    status="error",
                    message=f"未找到对应的处理器: {original_intent_type}",
                    requires_confirmation=False,
                    data={}
                )
            
            # 7. 构建新的 IntentResult（包含选中的零件）
            # 🔑 关键：将选中的零件 ID 注入到 parameters 中
            new_parameters = parsed_intent.get("parameters", {}).copy()
            
            # 提取选中零件的 subgraph_id
            selected_subgraph_ids = []
            for candidate in selected_candidates:
                source = candidate.get("_source", {})
                subgraph_id = source.get("subgraph_id")
                if subgraph_id:
                    selected_subgraph_ids.append(subgraph_id)
            
            logger.info(f"📋 选中的 subgraph_ids: {selected_subgraph_ids}")
            
            # 根据原始意图类型，设置正确的参数
            if original_intent_type in ["FEATURE_RECOGNITION", "PRICE_CALCULATION", "WEIGHT_PRICE_CALCULATION"]:
                # 这些意图使用 subgraph_ids（列表）
                new_parameters["subgraph_ids"] = selected_subgraph_ids
            elif original_intent_type == "DATA_MODIFICATION":
                # 数据修改意图，保留原始参数，但添加 target_subgraph_ids
                new_parameters["target_subgraph_ids"] = selected_subgraph_ids
            else:
                # 其他意图，使用 subgraph_id（单个）
                if selected_subgraph_ids:
                    new_parameters["subgraph_id"] = selected_subgraph_ids[0]
            
            new_intent_result = IntentResult(
                intent_type=original_intent_type,
                confidence=parsed_intent.get("confidence", 1.0),
                parameters=new_parameters,
                raw_message=original_message
            )
            
            # 8. 调用原始 Handler 处理
            logger.info(f"🔧 调用原始 Handler: {original_handler.__class__.__name__}")
            
            result = await original_handler.handle(
                new_intent_result,
                job_id,
                context,
                db_session
            )
            
            logger.info(f"✅ 确认响应处理完成: status={result.status}")
            
            return result
        
        except Exception as e:
            logger.error(f"❌ 处理确认响应失败: {e}", exc_info=True)
            return ActionResult(
                status="error",
                message=f"处理确认响应失败: {str(e)}",
                requires_confirmation=False,
                data={}
            )
