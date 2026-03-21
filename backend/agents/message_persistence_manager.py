"""
消息持久化管理器
负责人：系统架构组

职责：
1. 管理 WebSocket 消息的持久化逻辑
2. 判断哪些消息需要持久化
3. 调用格式化器和数据库接口
"""
from typing import Optional
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from api_gateway.utils.message_formatter import format_websocket_message
from api_gateway.utils.chat_logger import log_system_message

logger = logging.getLogger(__name__)


class MessagePersistenceManager:
    """消息持久化管理器"""
    
    # 需要持久化的消息类型（高业务价值）
    PERSISTABLE_MESSAGES = {
        'need_user_input',           # P0 - 交互卡片
        'modification_confirmation',  # P0 - 修改确认
        'review_data',               # P1 - 审核数据
        'review_display_view',       # P1 - 展示视图（新增）
        'completion_request',        # P1 - 补全请求（新增）
        'review_completed',          # P1 - 审核完成
        'operation_completed',       # P2 - 操作完成
        'system_message',            # P2 - 系统消息（新增）
        'progress',                  # P3 - 任务进度
    }
    
    def __init__(self):
        """初始化持久化管理器"""
        self.enabled = True  # 持久化开关（用于灰度发布）
    
    async def push_and_persist(
        self,
        job_id: str,
        ws_message: dict,
        db_session: Optional[AsyncSession] = None,
        ws_manager = None
    ):
        """
        推送并持久化消息
        
        Args:
            job_id: 任务ID
            ws_message: WebSocket 消息
            db_session: 数据库会话（可选）
            ws_manager: WebSocket 管理器（可选）
        
        Workflow:
            1. WebSocket 推送（实时）
            2. 判断是否需要持久化
            3. 格式化消息
            4. 写入数据库（异步）
        """
        try:
            # 1. WebSocket 推送（优先，确保实时性）
            if ws_manager:
                await ws_manager.broadcast(job_id, ws_message)
                logger.debug(f"✅ WebSocket 推送成功: job_id={job_id}, type={ws_message.get('type')}")
            
            # 2. 判断是否需要持久化
            if not self.should_persist(ws_message):
                logger.debug(f"⏭️  消息无需持久化: type={ws_message.get('type')}")
                return
            
            # 3. 持久化（如果提供了数据库会话）
            if db_session:
                await self.persist_message(job_id, ws_message, db_session)
            else:
                logger.warning(f"⚠️  未提供数据库会话，跳过持久化: job_id={job_id}")
        
        except Exception as e:
            # 持久化失败不应影响主流程
            logger.error(f"❌ 消息持久化失败: {e}", exc_info=True)
    
    def should_persist(self, ws_message: dict) -> bool:
        """
        判断消息是否需要持久化
        
        Args:
            ws_message: WebSocket 消息
        
        Returns:
            是否需要持久化
        """
        if not self.enabled:
            return False
        
        message_type = ws_message.get('type')
        return message_type in self.PERSISTABLE_MESSAGES
    
    async def persist_message(
        self,
        job_id: str,
        ws_message: dict,
        db_session: AsyncSession
    ):
        """
        持久化消息到数据库
        
        Args:
            job_id: 任务ID（作为 session_id）
            ws_message: WebSocket 消息
            db_session: 数据库会话
        """
        try:
            # 1. 格式化消息
            content, metadata = format_websocket_message(ws_message)
            
            logger.info(f"📝 持久化消息: job_id={job_id}, type={ws_message.get('type')}")
            logger.debug(f"   content: {content[:100]}...")
            
            # 2. 写入数据库
            await log_system_message(
                db_session=db_session,
                session_id=job_id,
                content=content,
                metadata=metadata
            )
            
            logger.info(f"✅ 消息持久化成功: job_id={job_id}, type={ws_message.get('type')}")
        
        except Exception as e:
            logger.error(f"❌ 持久化消息失败: {e}", exc_info=True)
            raise
    
    def enable(self):
        """启用持久化"""
        self.enabled = True
        logger.info("✅ 消息持久化已启用")
    
    def disable(self):
        """禁用持久化（用于灰度发布或紧急回滚）"""
        self.enabled = False
        logger.warning("⚠️  消息持久化已禁用")


# 全局单例
_persistence_manager = None


def get_persistence_manager() -> MessagePersistenceManager:
    """
    获取持久化管理器单例
    
    Returns:
        MessagePersistenceManager 实例
    """
    global _persistence_manager
    
    if _persistence_manager is None:
        _persistence_manager = MessagePersistenceManager()
    
    return _persistence_manager
