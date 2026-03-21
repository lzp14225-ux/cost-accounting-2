"""
Clarification Agent - 输入澄清代理
负责人：人员B2

职责：
主控制器，协调整个澄清流程
"""
import logging
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .clarification_models import ClarificationResult
from .input_validator import InputValidator
from .confidence_scorer import ConfidenceScorer
from .confirmation_generator import ConfirmationGenerator
from .response_handler import ResponseHandler
from .clarification_history import ClarificationHistory

logger = logging.getLogger(__name__)


class ClarificationAgent:
    """输入澄清代理"""
    
    def __init__(
        self,
        confidence_threshold: float = 0.75,
        enable_history: bool = True
    ):
        """
        初始化 ClarificationAgent
        
        Args:
            confidence_threshold: 置信度阈值，低于此值触发澄清
            enable_history: 是否启用历史学习
        """
        self.confidence_threshold = confidence_threshold
        self.enable_history = enable_history
        
        # 初始化组件
        self.validator = InputValidator()
        self.scorer = ConfidenceScorer()
        self.generator = ConfirmationGenerator()
        self.response_handler = ResponseHandler()
        self.history = ClarificationHistory() if enable_history else None
        
        logger.info(f"✅ ClarificationAgent 初始化完成: threshold={confidence_threshold}, history={enable_history}")
    
    async def process_input(
        self,
        user_input: str,
        job_id: str,
        session_id: str,
        db: AsyncSession
    ) -> ClarificationResult:
        """
        处理用户输入，决定是否需要澄清
        
        流程：
        1. 验证输入（InputValidator）
        2. 检查历史匹配（ClarificationHistory）
        3. 计算置信度（ConfidenceScorer）
        4. 决定是否需要澄清
        5. 如果需要，生成确认消息（ConfirmationGenerator）
        
        Args:
            user_input: 用户输入
            job_id: 任务ID
            session_id: 会话ID
            db: 数据库会话
        
        Returns:
            ClarificationResult: 澄清处理结果
        """
        logger.info(f"🔍 处理输入: {user_input[:50]}...")
        
        try:
            # 1. 验证输入
            logger.info(f"📋 步骤1: 验证输入")
            validation_result = await self.validator.validate(user_input, job_id, db)
            
            # 🆕 1.3. 检查是否有严重错误（ERROR 级别）
            has_critical_errors = any(
                issue.severity == "error" 
                for issue in validation_result.issues
            )
            
            if has_critical_errors:
                # 有严重错误，直接返回错误信息，不触发澄清
                error_messages = [
                    issue.message 
                    for issue in validation_result.issues 
                    if issue.severity == "error"
                ]
                suggestions = validation_result.suggestions
                
                logger.warning(f"❌ 发现严重错误，不触发澄清: {error_messages}")
                
                # 构建错误消息
                error_text = "\n".join(error_messages)
                if suggestions:
                    error_text += "\n\n" + "\n".join(suggestions)
                
                return ClarificationResult(
                    needs_clarification=False,
                    confidence_score=0.0,
                    parsed_entities=validation_result.extracted_entities,
                    confirmation_message=error_text,  # 返回错误消息
                    validation_result=validation_result
                )
            
            # 🆕 1.5. 检查是否是特殊操作（不需要澄清）
            extracted_action = validation_result.extracted_entities.get("action")
            special_actions = [
                "weight_price_calculation",  # 按重量计算
                "feature_recognition",        # 重新识别特征
                "price_calculation",          # 重新计算价格
                "weight_price_query",         # 查询按重量计算详情
                "query"                       # 查询详情
            ]
            
            if extracted_action in special_actions:
                logger.info(f"✅ 检测到特殊操作: {extracted_action}，跳过澄清流程")
                return ClarificationResult(
                    needs_clarification=False,
                    confidence_score=1.0,  # 特殊操作不需要澄清
                    normalized_input=user_input,
                    parsed_entities=validation_result.extracted_entities
                )
            
            # 2. 检查历史匹配
            history_match = None
            if self.enable_history and self.history:
                logger.info(f"📚 步骤2: 检查历史匹配")
                history_match = self.history.find_similar(session_id, user_input)
                if history_match:
                    logger.info(f"✅ 找到历史匹配: similarity={history_match.similarity:.2f}")
            
            # 3. 计算置信度
            logger.info(f"📊 步骤3: 计算置信度")
            confidence_score = self.scorer.calculate_score(
                validation_result,
                user_input,
                history_match
            )
            
            logger.info(f"置信度分数: {confidence_score:.2f}, 阈值: {self.confidence_threshold}")
            
            # 4. 决定是否需要澄清
            needs_clarification = confidence_score < self.confidence_threshold
            
            if not needs_clarification:
                # 高置信度，不需要澄清
                logger.info(f"✅ 置信度足够高，不需要澄清")
                
                # 如果有历史匹配，使用历史的标准化输入
                if history_match:
                    normalized_input = history_match.entry.normalized_input
                else:
                    # 否则使用原始输入
                    normalized_input = user_input
                
                return ClarificationResult(
                    needs_clarification=False,
                    confidence_score=confidence_score,
                    parsed_entities=validation_result.extracted_entities,
                    normalized_input=normalized_input,
                    validation_result=validation_result
                )
            
            # 5. 需要澄清，生成确认消息
            logger.info(f"⚠️  置信度较低，需要澄清")
            
            confirmation_message = self.generator.generate(
                validation_result,
                user_input
            )
            
            # 生成澄清ID
            clarification_id = str(uuid.uuid4())
            
            logger.info(f"✅ 澄清消息生成完成: clarification_id={clarification_id}")
            
            return ClarificationResult(
                needs_clarification=True,
                confidence_score=confidence_score,
                parsed_entities=validation_result.extracted_entities,
                confirmation_message=confirmation_message.message_text,
                clarification_id=clarification_id,
                validation_result=validation_result
            )
        
        except Exception as e:
            logger.error(f"❌ 处理输入失败: {e}", exc_info=True)
            
            # 发生错误时，跳过澄清，直接使用原始输入
            return ClarificationResult(
                needs_clarification=False,
                confidence_score=0.0,
                parsed_entities={},
                normalized_input=user_input,
                validation_result=None
            )
    
    async def handle_user_response(
        self,
        clarification_id: str,
        response_type: str,  # "confirm", "reject", "modify"
        response_data: Optional[dict] = None
    ) -> dict:
        """
        处理用户对澄清的响应
        
        Args:
            clarification_id: 澄清ID
            response_type: 响应类型
            response_data: 响应数据（modify 时需要）
        
        Returns:
            处理结果
        """
        logger.info(f"📥 处理用户响应: type={response_type}, id={clarification_id}")
        
        try:
            if response_type == "confirm":
                # 确认
                parsed_entities = response_data.get("parsed_entities", {})
                result = await self.response_handler.handle_confirm(
                    clarification_id,
                    parsed_entities
                )
                
                # 添加到历史
                if self.enable_history and self.history and result.success:
                    session_id = response_data.get("session_id")
                    original_input = response_data.get("original_input")
                    if session_id and original_input:
                        self.history.add_entry(
                            session_id,
                            original_input,
                            result.normalized_input,
                            parsed_entities
                        )
                
                return {
                    "status": "confirmed",
                    "normalized_input": result.normalized_input
                }
            
            elif response_type == "reject":
                # 拒绝
                result = await self.response_handler.handle_reject(clarification_id)
                
                return {
                    "status": "rejected",
                    "error_message": result.error_message
                }
            
            elif response_type == "modify":
                # 修改
                modifications = response_data.get("modifications", {})
                result = await self.response_handler.handle_modify(
                    clarification_id,
                    modifications
                )
                
                if result.requires_new_clarification:
                    return {
                        "status": "requires_new_clarification",
                        "error_message": result.error_message
                    }
                else:
                    return {
                        "status": "modified",
                        "normalized_input": result.normalized_input
                    }
            
            else:
                logger.error(f"❌ 未知的响应类型: {response_type}")
                return {
                    "status": "error",
                    "error_message": f"未知的响应类型: {response_type}"
                }
        
        except Exception as e:
            logger.error(f"❌ 处理响应失败: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"处理响应失败: {str(e)}"
            }
