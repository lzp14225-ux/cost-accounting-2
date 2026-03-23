"""
审核系统路由 (Review Router)
负责人：人员B2

职责：
1. 启动审核流程
2. 处理用户修改
3. 确认修改
4. 查询审核状态

阶段2.1实现
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from shared.database import get_db, AsyncSessionLocal
from ..auth import get_current_user
from agents.interaction_agent import InteractionAgent
from api_gateway.utils.chat_logger import (
    ensure_session_exists,
    log_system_message,
    log_user_message,
    log_assistant_message
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/review", tags=["review"])


async def _persist_chat_messages(
    session_id: str,
    job_id: str,
    user_id: str,
    action: str,
    user_content: Optional[str] = None,
    assistant_content: Optional[str] = None,
    assistant_metadata: Optional[dict] = None,
):
    """Use a short-lived session for chat logging to avoid blocking the main review flow."""
    async with AsyncSessionLocal() as chat_db:
        try:
            await ensure_session_exists(
                chat_db,
                session_id=session_id,
                job_id=job_id,
                user_id=user_id,
                metadata={"action": action}
            )

            if user_content is not None:
                await log_user_message(
                    chat_db,
                    session_id=session_id,
                    content=user_content,
                    metadata={"user_id": user_id, "action": action}
                )

            if assistant_content is not None:
                await log_assistant_message(
                    chat_db,
                    session_id=session_id,
                    content=assistant_content,
                    metadata=assistant_metadata or {"action": action}
                )

            await chat_db.commit()
        except Exception:
            await chat_db.rollback()
            raise


# ========== 请求模型 ==========

class StartReviewRequest(BaseModel):
    """启动审核请求"""
    job_id: str = Field(..., description="任务ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }


class ModificationRequest(BaseModel):
    """修改请求"""
    modification_text: str = Field(..., description="自然语言修改指令", min_length=1)
    
    class Config:
        json_schema_extra = {
            "example": {
                "modification_text": "将 UP01 的材质改为 718"
            }
        }


class ClarificationResponse(BaseModel):
    """澄清响应请求"""
    response_type: str = Field(..., description="响应类型: confirm, reject, modify")
    modifications: Optional[dict] = Field(None, description="修改内容（仅当 response_type=modify 时需要）")
    
    class Config:
        json_schema_extra = {
            "example": {
                "response_type": "confirm",
                "modifications": None
            }
        }
    
    class Config:
        json_schema_extra = {
            "example": {
                "modification_text": "将 UP01 的材质改为 718"
            }
        }


class ConfirmRequest(BaseModel):
    """确认请求（可选，用于扩展）"""
    comment: Optional[str] = Field(None, description="确认备注")
    
    class Config:
        json_schema_extra = {
            "example": {
                "comment": "审核通过"
            }
        }


# ========== 路由处理器 ==========

@router.post("/start")
async def start_review(
    request: StartReviewRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    启动审核流程
    
    功能：
    1. 查询 3 个表的数据
    2. 保存到 Redis
    3. 推送到前端（WebSocket）
    4. 获取分布式锁
    
    Args:
        request: 启动审核请求
        current_user: 当前用户（从JWT获取）
        db: 数据库会话
    
    Returns:
        {
            "status": "ok",
            "message": "审核已启动",
            "data": {
                "job_id": "xxx",
                "features_count": 10,
                "price_snapshots_count": 5,
                "subgraphs_count": 2
            }
        }
    
    Raises:
        400: 参数错误
        403: 权限不足
        409: 任务正在被其他用户审核
        500: 服务器错误
    """
    try:
        logger.info(f"📋 启动审核: job_id={request.job_id}, user_id={current_user['user_id']}")
        
        # 1. 确保会话存在
        await ensure_session_exists(
            db,
            session_id=request.job_id,
            job_id=request.job_id,
            user_id=current_user["user_id"],
            metadata={"action": "start_review"}
        )
        
        # 2. 创建 InteractionAgent
        agent = InteractionAgent()
        
        # 3. 启动审核
        result = await agent.start_review(
            job_id=request.job_id,
            db_session=db
        )
        
        # 4. 检查结果
        if result.status == "error":
            # 根据错误类型返回不同的HTTP状态码
            if "正在被其他用户审核" in result.message:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "REVIEW_LOCKED",
                        "message": result.message
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "START_REVIEW_FAILED",
                        "message": result.message
                    }
                )
        
        # 🆕 不再记录审核启动消息（前端已通过 HTTP 响应知道启动成功）
        # 前端通过 HTTP 响应知道启动成功：
        # {"status": "ok", "message": "审核流程已启动", "data": {...}}
        # 不需要再记录系统消息
        
        # await log_system_message(
        #     db,
        #     session_id=request.job_id,
        #     content=f"审核已启动，共查询到 {result.data.get('subgraphs_count', 0)} 条子图数据",
        #     metadata={
        #         "action": "start_review",
        #         "data_summary": {
        #             "features": result.data.get('features_count', 0),
        #             "price_snapshots": result.data.get('price_snapshots_count', 0),
        #             "subgraphs": result.data.get('subgraphs_count', 0)
        #         }
        #     }
        # )
        
        # 6. 提交数据库事务（保存会话和消息）
        await db.commit()
        
        logger.info(f"✅ 审核启动成功: job_id={request.job_id}")
        
        return {
            "status": "ok",
            "message": result.message,
            "data": result.data
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 启动审核异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )


@router.post("/{job_id}/modify")
async def modify_review(
    job_id: str,
    request: ModificationRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    提交修改指令（集成输入澄清和意图识别）
    
    功能：
    1. 🆕 输入澄清检查（如果输入不规范）
    2. 识别用户意图（数据修改、特征识别、价格计算、查询详情、普通聊天）
    3. 根据意图类型执行相应操作
    4. 保存到 Redis
    5. 推送确认消息到前端（如果需要确认）
    
    Args:
        job_id: 任务ID
        request: 修改请求
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        {
            "status": "ok" | "clarification_needed",
            "intent": "DATA_MODIFICATION",  # 意图类型
            "message": "修改已应用，等待确认",
            "requires_confirmation": true,  # 是否需要确认
            "clarification_id": "uuid",  # 🆕 澄清ID（如果需要澄清）
            "confidence_score": 0.65,  # 🆕 置信度分数
            "data": {
                "modification_id": "mod-uuid",
                "parsed_changes": [...],
                ...
            }
        }
    
    Raises:
        400: 参数错误或解析失败
        404: 审核会话不存在
        500: 服务器错误
    """
    try:
        logger.info(f"✏️ 处理修改: job_id={job_id}, user_id={current_user['user_id']}")
        logger.debug(f"修改内容: {request.modification_text}")
        
        # 1. 确保会话存在
        logger.info(f"开始写入修改会话消息: job_id={job_id}")
        await _persist_chat_messages(
            session_id=job_id,
            job_id=job_id,
            user_id=current_user["user_id"],
            action="modify",
            user_content=request.modification_text
        )
        logger.info(f"修改会话消息写入完成: job_id={job_id}")
        
        # 🆕 2.5.5. 数字选择检测（检查是否是选择澄清选项的数字）
        logger.info(f"🔍 步骤2.5.5: 数字选择检测")
        from agents.number_selection_handler import NumberSelectionHandler
        
        try:
            number_handler = NumberSelectionHandler()
            
            # 检测并处理数字选择
            number_result = await number_handler.handle_number_selection(
                user_input=request.modification_text,
                session_id=job_id,
                db=db
            )
            
            if number_result and number_result.get("is_number_selection"):
                logger.info(f"✅ 检测到数字选择: {number_result.get('selection_number')} → {number_result.get('selected_value')}")
                
                # 使用标准化输入替换原始输入
                standardized_input = number_result.get("standardized_input")
                clarification_id = number_result.get("clarification_id")
                
                # 自动确认澄清
                if clarification_id:
                    from agents.clarification_state import get_state_manager
                    
                    # 更新澄清状态中的实体（添加选择的值）
                    parsed_entities = number_result.get("parsed_entities", {})
                    parsed_entities["value"] = number_result.get("selected_value")
                    parsed_entities["_best_match"] = number_result.get("selected_value")
                    
                    # 删除澄清状态（已处理完成）
                    state_manager = get_state_manager()
                    await state_manager.delete_clarification_state(clarification_id)
                    
                    logger.info(f"✅ 澄清已自动确认，使用标准化输入: {standardized_input}")
                    
                    # 记录用户选择消息（更新之前记录的消息内容）
                    await log_assistant_message(
                        db,
                        session_id=job_id,
                        content=f"您选择了：{number_result.get('selected_value')}",
                        metadata={
                            "action": "number_selection_confirmed",
                            "selection_number": number_result.get("selection_number"),
                            "selected_value": number_result.get("selected_value")
                        }
                    )
                    
                    await db.commit()
                    
                    # 使用标准化输入继续处理
                    request.modification_text = standardized_input
        
        except Exception as number_error:
            logger.error(f"❌ 数字选择检测失败: {number_error}, 继续正常流程", exc_info=True)
            # 失败不阻塞，继续正常流程
        
        # 🆕 2.6. LLM 确认检测（检查是否是对澄清的确认回复）
        logger.info(f"🔍 步骤2.6: LLM 确认检测")
        from agents.llm_confirmation_detector import LLMConfirmationDetector
        
        try:
            confirmation_detector = LLMConfirmationDetector()
            
            # 获取聊天历史
            chat_history = await confirmation_detector.get_chat_history(
                session_id=job_id,
                db=db,
                limit=10
            )
            
            logger.info(f"📚 获取到 {len(chat_history)} 条聊天历史")
            for i, msg in enumerate(chat_history[-3:]):  # 只显示最近3条
                logger.debug(f"  消息 {i}: role={msg.get('role')}, content={msg.get('content', '')[:50]}..., metadata={msg.get('metadata', {})}")
            
            # 检测是否是确认性回复
            confirmation_result = await confirmation_detector.detect_confirmation_intent(
                user_input=request.modification_text,
                chat_history=chat_history,
                session_id=job_id
            )
            
            if confirmation_result and confirmation_result.get("is_confirmation"):
                logger.info(f"✅ 检测到确认性回复: {confirmation_result.get('response_type')}")
                
                # 自动调用确认接口
                clarification_id = confirmation_result.get("clarification_id")
                response_type = confirmation_result.get("response_type")
                
                if clarification_id and response_type:
                    # 重定向到确认接口
                    from pydantic import BaseModel
                    from typing import Optional
                    
                    class AutoConfirmResponse(BaseModel):
                        response_type: str
                        modifications: Optional[dict] = None
                    
                    auto_response = AutoConfirmResponse(
                        response_type=response_type,
                        modifications=None
                    )
                    
                    logger.info(f"🔄 自动调用确认接口: clarification_id={clarification_id}")
                    
                    return await respond_to_clarification(
                        job_id=job_id,
                        clarification_id=clarification_id,
                        response=auto_response,
                        current_user=current_user,
                        db=db
                    )
        
        except Exception as llm_error:
            logger.error(f"❌ LLM 确认检测失败: {llm_error}, 继续正常流程", exc_info=True)
            # 失败不阻塞，继续正常流程
        
        # 🆕 3. 输入澄清检查（在意图识别之前）
        logger.info(f"🔍 步骤3: 输入澄清检查")
        from agents.clarification_agent import ClarificationAgent
        from agents.clarification_state import get_state_manager
        
        try:
            clarification_agent = ClarificationAgent(
                confidence_threshold=0.75,
                enable_history=True
            )
            
            clarification_result = await clarification_agent.process_input(
                user_input=request.modification_text,
                job_id=job_id,
                session_id=job_id,
                db=db
            )
            
            # 🆕 如果需要澄清，保存状态并返回确认消息
            if clarification_result.needs_clarification:
                logger.info(f"⚠️  需要澄清: confidence={clarification_result.confidence_score:.2f}")
                
                # 保存澄清状态到 Redis
                state_manager = get_state_manager()
                await state_manager.save_clarification_state(
                    clarification_result.clarification_id,
                    {
                        "job_id": job_id,
                        "session_id": job_id,
                        "user_id": current_user["user_id"],
                        "original_input": request.modification_text,
                        "parsed_entities": clarification_result.parsed_entities,
                        "confidence_score": clarification_result.confidence_score,
                        "validation_result": clarification_result.validation_result.to_dict() if clarification_result.validation_result else None
                    },
                    ttl=300  # 5分钟过期
                )
                
                # 记录助手回复（澄清消息）
                await log_assistant_message(
                    db,
                    session_id=job_id,
                    content=clarification_result.confirmation_message,
                    metadata={
                        "action": "clarification_request",
                        "clarification_id": clarification_result.clarification_id,
                        "confidence_score": clarification_result.confidence_score
                    }
                )
                
                await db.commit()
                
                logger.info(f"✅ 澄清消息已发送")
                
                # 返回澄清响应
                return {
                    "status": "clarification_needed",
                    "clarification_id": clarification_result.clarification_id,
                    "confidence_score": clarification_result.confidence_score,
                    "message": clarification_result.confirmation_message,
                    "parsed_interpretation": clarification_result.parsed_entities,
                    "data": {
                        "requires_confirmation": True,
                        "clarification_type": "input_validation"
                    }
                }
            
            # 🆕 不需要澄清，使用标准化输入继续处理
            logger.info(f"✅ 输入规范，置信度: {clarification_result.confidence_score:.2f}")
            normalized_text = clarification_result.normalized_input or request.modification_text
            
        except Exception as clarification_error:
            # 澄清失败，记录错误但不阻塞流程
            logger.error(f"❌ 输入澄清失败: {clarification_error}, 跳过澄清继续处理", exc_info=True)
            normalized_text = request.modification_text
        
        # 4. 创建 InteractionAgent
        agent = InteractionAgent()
        
        # 5. 处理修改（集成意图识别）- 使用标准化输入
        result = await agent.handle_modification(
            job_id=job_id,
            modification_text=normalized_text,  # 🆕 使用标准化输入
            user_id=current_user["user_id"],
            db_session=db
        )
        
        # 6. 检查结果
        if result.status == "error":
            if "未找到审核会话" in result.message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "SESSION_NOT_FOUND",
                        "message": result.message
                    }
                )
            elif "解析失败" in result.message:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "PARSE_FAILED",
                        "message": result.message
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "MODIFICATION_FAILED",
                        "message": result.message
                    }
                )
        
        # 7. 记录助手回复
        await _persist_chat_messages(
            session_id=job_id,
            job_id=job_id,
            user_id=current_user["user_id"],
            action="modify_response",
            assistant_content=result.message,
            assistant_metadata={
                "intent": result.data.get('intent') if result.data else None,
                "requires_confirmation": result.data.get('requires_confirmation') if result.data else False,
                "action": "modify_response"
            }
        )
        
        logger.info(f"✅ 修改处理成功: job_id={job_id}, intent={result.data.get('intent')}")
        
        # 8. 返回结果（包含 intent 和 requires_confirmation）
        return {
            "status": "ok",
            "intent": result.data.get("intent") if result.data else None,  # 新增
            "message": result.message,
            "requires_confirmation": result.data.get("requires_confirmation") if result.data else False,  # 新增
            "data": result.data
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 处理修改异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )


@router.post("/{job_id}/confirm")
async def confirm_review(
    job_id: str,
    request: ConfirmRequest = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    确认修改并保存到数据库
    
    功能：
    1. 获取 Redis 中的临时数据
    2. 更新数据库（事务）
    3. 释放分布式锁
    4. 清理 Redis
    5. 推送完成消息
    
    Args:
        job_id: 任务ID
        request: 确认请求（可选）
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        {
            "status": "ok",
            "message": "审核已完成，数据已保存",
            "data": {
                "modifications_count": 3,
                "updated_tables": ["features", "subgraphs"]
            }
        }
    
    Raises:
        404: 审核会话不存在
        500: 服务器错误
    """
    try:
        logger.info(f"✅ 确认审核: job_id={job_id}, user_id={current_user['user_id']}")
        
        # 1. 确保会话存在
        logger.info(f"📝 开始确保会话存在...")
        await ensure_session_exists(
            db,
            session_id=job_id,
            job_id=job_id,
            user_id=current_user["user_id"],
            metadata={"action": "confirm"}
        )
        logger.info(f"✅ 会话检查完成")
        
        # 2. 创建 InteractionAgent
        agent = InteractionAgent()
        
        # 3. 确认修改
        result = await agent.confirm_changes(
            job_id=job_id,
            user_id=current_user["user_id"],
            db_session=db
        )
        
        # 检查结果
        if result.status == "error":
            # 🆕 版本冲突
            if "数据已被其他系统修改" in result.message:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "VERSION_CONFLICT",
                        "message": result.message,
                        "conflicts": result.data.get("conflicts", []),
                        "suggestion": "数据已被修改，请点击刷新重新加载数据"
                    }
                )
            elif "未找到审核会话" in result.message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "SESSION_NOT_FOUND",
                        "message": result.message
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "CONFIRM_FAILED",
                        "message": result.message
                    }
                )
        
        # 🆕 不再记录重复的系统消息（前端已通过 WebSocket 收到 operation_completed）
        # 前端通过以下方式知道操作成功：
        # 1. HTTP 响应：{"status": "ok", "message": "..."}
        # 2. WebSocket 消息：{"type": "operation_completed", ...}
        # 不需要再记录一条重复的系统消息
        
        # await log_system_message(
        #     db,
        #     session_id=job_id,
        #     content=f"修改已确认并保存到数据库，共 {result.data.get('modifications_count', 0)} 处修改",
        #     metadata={
        #         "action": "confirm",
        #         "modifications_count": result.data.get('modifications_count', 0)
        #     }
        # )
        
        # 提交数据库事务（保存消息）
        await db.commit()
        
        logger.info(f"✅ 审核确认成功: job_id={job_id}, modifications={result.data.get('modifications_count')}")
        
        return {
            "status": "ok",
            "message": result.message,
            "data": result.data
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 确认审核异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )




@router.post("/{job_id}/refresh")
async def refresh_review_data(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    刷新审核数据
    
    功能：
    1. 重新从数据库查询 4 个表的数据
    2. 更新 Redis 中的数据
    3. 推送最新数据到前端
    4. 保持锁和状态不变
    
    适用场景：
    - 执行了"重新识别特征"或"重新计算"后，需要刷新数据
    - 数据库数据已更新，需要同步到 Redis
    
    Args:
        job_id: 任务ID
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        {
            "status": "ok",
            "message": "数据已刷新",
            "data": {
                "job_id": "xxx",
                "refresh_count": 1,
                "features_count": 10,
                "subgraphs_count": 5,
                ...
            }
        }
    
    Raises:
        404: 审核会话不存在
        500: 服务器错误
    """
    try:
        logger.info(f"🔄 刷新审核数据: job_id={job_id}, user_id={current_user['user_id']}")
        
        # 创建 InteractionAgent
        agent = InteractionAgent()
        
        # 刷新数据
        result = await agent.refresh_data(
            job_id=job_id,
            db_session=db
        )
        
        # 检查结果
        if result.status == "error":
            if "不存在或已过期" in result.message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "SESSION_NOT_FOUND",
                        "message": result.message
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "REFRESH_FAILED",
                        "message": result.message
                    }
                )
        
        # 提交数据库事务（保存持久化的消息）
        await db.commit()
        
        logger.info(f"✅ 数据刷新成功: job_id={job_id}")
        
        return {
            "status": "ok",
            "message": result.message,
            "data": result.data
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 刷新数据异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )


@router.get("/{job_id}/status")
async def get_review_status(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    查询审核状态
    
    功能：
    1. 从 Redis 获取审核状态
    2. 返回当前状态和修改历史
    
    Args:
        job_id: 任务ID
        current_user: 当前用户
    
    Returns:
        {
            "status": "ok",
            "data": {
                "job_id": "xxx",
                "review_status": "reviewing",
                "is_locked": true,
                "modifications_count": 2,
                "created_at": "2026-01-15T10:00:00",
                "last_modified_at": "2026-01-15T10:05:00"
            }
        }
    
    Raises:
        404: 审核会话不存在
        500: 服务器错误
    """
    try:
        logger.info(f"📊 查询审核状态: job_id={job_id}, user_id={current_user['user_id']}")
        
        # 创建 InteractionAgent
        agent = InteractionAgent()
        
        # 获取状态
        state = await agent.get_review_state(job_id)
        
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "SESSION_NOT_FOUND",
                    "message": "未找到审核会话"
                }
            )
        
        # 检查锁状态
        is_locked = await agent.check_lock(job_id)
        
        logger.info(f"✅ 状态查询成功: job_id={job_id}, status={state.get('status')}")
        
        return {
            "status": "ok",
            "data": {
                "job_id": job_id,
                "review_status": state.get("status"),
                "is_locked": is_locked,
                "modifications_count": len(state.get("modifications", [])),
                "created_at": state.get("created_at"),
                "last_modified_at": state.get("last_modified_at")
            }
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 查询状态异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )



@router.post("/{job_id}/clarification/{clarification_id}/respond")
async def respond_to_clarification(
    job_id: str,
    clarification_id: str,
    response: ClarificationResponse,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    响应澄清确认
    
    功能：
    1. 获取澄清状态
    2. 处理用户响应（确认/拒绝/修改）
    3. 根据响应类型执行相应操作
    
    Args:
        job_id: 任务ID
        clarification_id: 澄清ID
        response: 用户响应
            {
                "response_type": "confirm" | "reject" | "modify",
                "modifications": {...}  # 仅当 response_type="modify" 时需要
            }
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        根据响应类型返回不同结果：
        - confirm: 继续处理修改，返回修改结果
        - reject: 返回错误，要求重新输入
        - modify: 返回新的澄清或继续处理
    
    Raises:
        404: 澄清状态不存在
        400: 参数错误
        500: 服务器错误
    """
    try:
        logger.info(f"📥 响应澄清: job_id={job_id}, clarification_id={clarification_id}, type={response.response_type}")
        
        # 1. 获取澄清状态
        from agents.clarification_state import get_state_manager
        from agents.clarification_agent import ClarificationAgent
        
        state_manager = get_state_manager()
        clarification_state = await state_manager.get_clarification_state(clarification_id)
        
        if not clarification_state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "CLARIFICATION_NOT_FOUND",
                    "message": "澄清状态不存在或已过期"
                }
            )
        
        # 2. 处理响应
        clarification_agent = ClarificationAgent()
        
        response_data = {
            "parsed_entities": clarification_state.get("parsed_entities", {}),
            "session_id": clarification_state.get("session_id"),
            "original_input": clarification_state.get("original_input"),
            "modifications": response.modifications
        }
        
        response_result = await clarification_agent.handle_user_response(
            clarification_id=clarification_id,
            response_type=response.response_type,
            response_data=response_data
        )
        
        # 3. 根据响应类型处理
        if response.response_type == "confirm":
            # 用户确认，使用标准化输入重新调用 modify 接口
            logger.info(f"✅ 用户确认澄清，使用标准化输入继续处理")
            
            normalized_input = response_result.get("normalized_input")
            
            # 删除澄清状态
            await state_manager.delete_clarification_state(clarification_id)
            
            # 重新调用 modify_review
            modification_request = ModificationRequest(modification_text=normalized_input)
            return await modify_review(
                job_id=job_id,
                request=modification_request,
                current_user=current_user,
                db=db
            )
        
        elif response.response_type == "reject":
            # 用户拒绝
            logger.info(f"❌ 用户拒绝澄清")
            
            # 删除澄清状态
            await state_manager.delete_clarification_state(clarification_id)
            
            return {
                "status": "rejected",
                "message": response_result.get("error_message", "请重新输入更清晰的指令")
            }
        
        elif response.response_type == "modify":
            # 用户修改
            logger.info(f"🔧 用户修改澄清")
            
            if response_result.get("status") == "requires_new_clarification":
                # 需要新的澄清
                return {
                    "status": "requires_new_clarification",
                    "message": response_result.get("error_message")
                }
            else:
                # 修改成功，使用新的标准化输入
                normalized_input = response_result.get("normalized_input")
                
                # 删除澄清状态
                await state_manager.delete_clarification_state(clarification_id)
                
                # 重新调用 modify_review
                modification_request = ModificationRequest(modification_text=normalized_input)
                return await modify_review(
                    job_id=job_id,
                    request=modification_request,
                    current_user=current_user,
                    db=db
                )
        
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "INVALID_RESPONSE_TYPE",
                    "message": f"无效的响应类型: {response.response_type}"
                }
            )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 响应澄清异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )
