"""
聊天日志辅助函数
负责人：人员B2

职责：
1. 简化聊天消息的保存
2. 提供统一的日志接口
"""
from typing import Dict, Any, Optional
import logging

from api_gateway.repositories.chat_history_repository import ChatHistoryRepository

logger = logging.getLogger(__name__)

# 全局实例
chat_history_repo = ChatHistoryRepository()


async def log_user_message(
    db_session,
    session_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    记录用户消息
    
    Args:
        db_session: 数据库会话
        session_id: 会话ID
        content: 消息内容
        metadata: 额外信息
    """
    try:
        await chat_history_repo.add_message(
            db_session,
            session_id=session_id,
            role="user",
            content=content,
            metadata=metadata
        )
        logger.debug(f"用户消息已记录: {session_id}")
    except Exception as e:
        logger.error(f"记录用户消息失败: {e}", exc_info=True)


async def log_assistant_message(
    db_session,
    session_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    记录AI助手回复
    
    Args:
        db_session: 数据库会话
        session_id: 会话ID
        content: 消息内容
        metadata: 额外信息
    """
    try:
        await chat_history_repo.add_message(
            db_session,
            session_id=session_id,
            role="assistant",
            content=content,
            metadata=metadata
        )
        logger.debug(f"助手回复已记录: {session_id}")
    except Exception as e:
        logger.error(f"记录助手回复失败: {e}", exc_info=True)


async def log_system_message(
    db_session,
    session_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    记录系统消息
    
    Args:
        db_session: 数据库会话
        session_id: 会话ID
        content: 消息内容
        metadata: 额外信息
    """
    try:
        await chat_history_repo.add_message(
            db_session,
            session_id=session_id,
            role="system",
            content=content,
            metadata=metadata
        )
        logger.debug(f"系统消息已记录: {session_id}")
    except Exception as e:
        logger.error(f"记录系统消息失败: {e}", exc_info=True)


async def ensure_session_exists(
    db_session,
    session_id: str,
    job_id: str,
    user_id: str,
    session_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    确保会话存在（如果不存在则创建）
    
    Args:
        db_session: 数据库会话
        session_id: 会话ID
        job_id: 任务ID
        user_id: 用户ID
        session_name: 会话名称（可选）
        metadata: 额外信息
    """
    try:
        logger.info(f"📝 开始检查会话: session_id={session_id}")
        
        # 检查会话是否存在
        logger.debug(f"查询会话信息...")
        session_info = await chat_history_repo.get_session_info(db_session, session_id)
        
        if not session_info:
            # 创建新会话
            logger.info(f"会话不存在，创建新会话...")
            await chat_history_repo.create_session(
                db_session,
                session_id=session_id,
                job_id=job_id,
                user_id=user_id,
                session_name=session_name,
                metadata=metadata
            )
            logger.info(f"✅ 会话已创建: {session_id}")
        else:
            logger.debug(f"✅ 会话已存在: {session_id}")
    
    except Exception as e:
        logger.error(f"❌ 确保会话存在失败: {e}", exc_info=True)
        # 不要抛出异常，让流程继续
