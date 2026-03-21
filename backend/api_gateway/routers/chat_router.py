"""
SSE 流式聊天路由 (Chat Router)
负责人：人员B2

职责：
1. 提供 SSE 流式聊天接口
2. 支持多轮对话
3. 实时流式输出 LLM 响应

学习主流方案：ChatGPT、豆包、Kimi
"""
import logging
import json
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from shared.database import get_db
from ..auth import get_current_user
from agents.interaction_agent import InteractionAgent
from api_gateway.utils.chat_logger import (
    ensure_session_exists,
    log_user_message,
    log_assistant_message
)
from api_gateway.repositories.chat_history_repository import ChatHistoryRepository

logger = logging.getLogger(__name__)

# 全局实例
chat_history_repo = ChatHistoryRepository()

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# ========== 请求模型 ==========

class Message(BaseModel):
    """聊天消息"""
    role: str = Field(..., description="角色：user 或 assistant")
    content: str = Field(..., description="消息内容")
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "将 UP01 的材质改为 718"
            }
        }


class ChatRequest(BaseModel):
    """聊天请求"""
    job_id: str = Field(..., description="任务ID")
    message: str = Field(..., description="用户消息", min_length=1)
    history: Optional[List[Message]] = Field(default=[], description="历史消息")
    stream: bool = Field(default=True, description="是否流式输出")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "message": "将 UP01 的材质改为 718",
                "history": [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好！我是审核助手，有什么可以帮你的？"}
                ],
                "stream": True
            }
        }


# ========== 路由处理器 ==========

@router.post("/completions")
async def chat_completions(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    SSE 流式聊天接口
    
    功能：
    1. 接收用户消息
    2. 调用 LLM 生成响应
    3. 流式输出响应内容
    4. 支持多轮对话
    
    Args:
        request: 聊天请求
        current_user: 当前用户
    
    Returns:
        SSE 流式响应：
        
        data: {"type": "start", "message_id": "xxx"}
        
        data: {"type": "content", "delta": "将"}
        data: {"type": "content", "delta": " UP01"}
        data: {"type": "content", "delta": " 的材质"}
        ...
        
        data: {"type": "done", "finish_reason": "stop"}
        
    Raises:
        400: 参数错误
        404: 审核会话不存在
        500: 服务器错误
    """
    try:
        logger.info(f"💬 聊天请求: job_id={request.job_id}, user_id={current_user['user_id']}")
        logger.debug(f"消息: {request.message}")
        
        # 1. 确保会话存在
        await ensure_session_exists(
            db,
            session_id=request.job_id,
            job_id=request.job_id,
            user_id=current_user["user_id"],
            metadata={"action": "chat"}
        )
        
        # 2. 记录用户消息
        await log_user_message(
            db,
            session_id=request.job_id,
            content=request.message,
            metadata={
                "user_id": current_user["user_id"],
                "stream": request.stream
            }
        )
        
        # 提交用户消息到数据库
        await db.commit()
        
        # 3. 创建 InteractionAgent
        agent = InteractionAgent()
        
        # 4. 检查审核会话是否存在
        state = await agent.get_review_state(request.job_id)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "SESSION_NOT_FOUND",
                    "message": "未找到审核会话，请先启动审核"
                }
            )
        
        # 🆕 阶段2：允许 COMPLETED 状态访问聊天（只读模式）
        from agents.review_status import ReviewStatus
        
        current_status = state.get("status")
        if current_status == ReviewStatus.COMPLETED:
            logger.info(f"💬 COMPLETED 状态下的聊天（只读模式）: job_id={request.job_id}")
        
        # 5. 流式响应
        if request.stream:
            async def event_stream():
                """SSE 事件流"""
                full_response = ""  # 收集完整响应用于记录
                db_stream = None  # 用于流式响应的独立数据库连接
                
                try:
                    # 1. 开始消息
                    import uuid
                    message_id = str(uuid.uuid4())
                    
                    yield f"data: {json.dumps({'type': 'start', 'message_id': message_id})}\n\n"
                    
                    # 2. 流式生成内容
                    async for chunk in agent.chat_stream(
                        job_id=request.job_id,
                        message=request.message,
                        history=[msg.dict() for msg in request.history],
                        current_data=state["data"]
                    ):
                        # 发送内容片段
                        yield f"data: {json.dumps({'type': 'content', 'delta': chunk})}\n\n"
                        full_response += chunk
                        
                        # 避免发送过快
                        await asyncio.sleep(0.01)
                    
                    # 3. 完成消息
                    yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'stop'})}\n\n"
                    
                    # 4. 记录助手回复（使用新的数据库连接）
                    from shared.database import get_db
                    async for db_stream in get_db():
                        try:
                            await log_assistant_message(
                                db_stream,
                                session_id=request.job_id,
                                content=full_response,
                                metadata={
                                    "message_id": message_id,
                                    "stream": True
                                }
                            )
                            await db_stream.commit()
                            logger.info(f"✅ 聊天完成: job_id={request.job_id}, message_id={message_id}")
                        finally:
                            await db_stream.close()
                        break
                
                except Exception as e:
                    logger.error(f"❌ 聊天流式输出错误: {e}", exc_info=True)
                    # 发送错误消息
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            
            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
                }
            )
        
        # 6. 非流式响应（一次性返回）
        else:
            response = await agent.chat(
                job_id=request.job_id,
                message=request.message,
                history=[msg.dict() for msg in request.history],
                current_data=state["data"]
            )
            
            # 记录助手回复
            await log_assistant_message(
                db,
                session_id=request.job_id,
                content=response,
                metadata={"stream": False}
            )
            
            # 提交数据库事务
            await db.commit()
            
            logger.info(f"✅ 聊天完成: job_id={request.job_id}")
            
            return {
                "status": "ok",
                "data": {
                    "message": response,
                    "finish_reason": "stop"
                }
            }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 聊天异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "chat"}



# ========== 聊天历史管理接口 ==========

@router.get("/history/{session_id}")
async def get_chat_history(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    获取聊天历史（支持分页）
    
    Args:
        session_id: 会话ID（通常与job_id相同）
        limit: 返回消息数量限制（默认100）
        offset: 偏移量，从第几条记录开始返回（默认0）
    
    Returns:
        {
            "session_id": "xxx",
            "messages": [
                {
                    "message_id": 1,
                    "role": "user",
                    "content": "将 UP01 的材质改为 718",
                    "timestamp": "2026-01-16T10:00:00",
                    "metadata": {}
                },
                ...
            ],
            "total_count": 150,      # 会话的真实总消息数
            "returned_count": 100,   # 本次返回的消息数
            "offset": 0,             # 当前偏移量
            "limit": 100,            # 当前限制数
            "has_more": true         # 是否还有更多消息
        }
    
    Examples:
        - 获取前100条: GET /history/{session_id}?limit=100&offset=0
        - 获取第101-200条: GET /history/{session_id}?limit=100&offset=100
        - 获取第201-300条: GET /history/{session_id}?limit=100&offset=200
    """
    try:
        # 获取会话信息
        session_info = await chat_history_repo.get_session_info(db, session_id)
        
        if not session_info:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        # 验证用户权限
        if session_info["user_id"] != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="无权访问此会话")
        
        # 获取历史消息（带分页）
        messages = await chat_history_repo.get_session_history(db, session_id, limit, offset)
        
        # 获取真实总消息数
        total_count = await chat_history_repo.get_session_message_count(db, session_id)
        
        # 计算是否还有更多消息
        has_more = (offset + len(messages)) < total_count
        
        return {
            "session_id": session_id,
            "session_info": session_info,
            "messages": messages,
            "total_count": total_count,        # 真实总消息数
            "returned_count": len(messages),   # 本次返回的消息数
            "offset": offset,                  # 当前偏移量
            "limit": limit,                    # 当前限制数
            "has_more": has_more               # 是否还有更多消息
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取聊天历史失败: {str(e)}")
        # 获取历史消息
        messages = await chat_history_repo.get_session_history(db, session_id, limit)
        
        # 获取真实总消息数
        total_count = await chat_history_repo.get_session_message_count(db, session_id)
        
        return {
            "session_id": session_id,
            "session_info": session_info,
            "messages": messages,
            "total_count": total_count,  # 真实总消息数
            "returned_count": len(messages)  # 本次返回的消息数
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取聊天历史失败: {str(e)}")


@router.get("/sessions")
async def get_user_sessions(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    获取用户的所有会话列表
    
    Args:
        limit: 返回会话数量限制
    
    Returns:
        {
            "sessions": [
                {
                    "session_id": "xxx",
                    "job_id": "xxx",
                    "created_at": "2026-01-16T10:00:00",
                    "updated_at": "2026-01-16T11:00:00",
                    "status": "active",
                    "message_count": 10,
                    "metadata": {"file_name": "xxx.xlsx"}
                },
                ...
            ]
        }
    """
    try:
        user_id = current_user["user_id"]
        
        sessions = await chat_history_repo.get_user_sessions(db, user_id, limit)
        
        return {
            "user_id": user_id,
            "sessions": sessions,
            "total_count": len(sessions)
        }
    
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.post("/sessions/{session_id}/archive")
async def archive_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    归档会话
    
    Args:
        session_id: 会话ID
    
    Returns:
        {"message": "会话已归档"}
    """
    try:
        # 获取会话信息
        session_info = await chat_history_repo.get_session_info(db, session_id)
        
        if not session_info:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        # 验证用户权限
        if session_info["user_id"] != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="无权操作此会话")
        
        # 归档会话
        success = await chat_history_repo.archive_session(db, session_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="归档会话失败")
        
        return {"message": "会话已归档", "session_id": session_id}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"归档会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"归档会话失败: {str(e)}")
