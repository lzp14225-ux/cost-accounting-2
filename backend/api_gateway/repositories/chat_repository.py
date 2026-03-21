"""
Chat Repository - 聊天消息仓库
负责人：人员B2

职责：
查询聊天历史消息
"""
import logging
from typing import List, Optional
from sqlalchemy import select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ChatMessage:
    """聊天消息数据类（用于返回）"""
    def __init__(self, message_id, session_id, role, content, metadata, created_at):
        self.message_id = message_id
        self.session_id = session_id
        self.role = role
        self.content = content
        self.metadata = metadata or {}
        self.created_at = created_at


class ChatRepository:
    """聊天消息仓库"""
    
    async def get_session_messages(
        self,
        db: AsyncSession,
        session_id: str,
        limit: int = 10
    ) -> List[ChatMessage]:
        """
        获取会话的聊天消息
        
        Args:
            db: 数据库会话
            session_id: 会话ID
            limit: 获取最近的 N 条消息
        
        Returns:
            聊天消息列表（按时间正序）
        """
        try:
            query = text("""
                SELECT message_id, session_id, role, content, metadata, timestamp as created_at
                FROM chat_messages
                WHERE session_id = :session_id
                ORDER BY timestamp DESC, message_id DESC
                LIMIT :limit
            """)
            
            result = await db.execute(
                query,
                {"session_id": session_id, "limit": limit}
            )
            rows = result.fetchall()
            
            # 转换为 ChatMessage 对象并反转顺序（使其按时间正序）
            messages = [
                ChatMessage(
                    message_id=row.message_id,
                    session_id=row.session_id,
                    role=row.role,
                    content=row.content,
                    metadata=row.metadata,
                    created_at=row.created_at
                )
                for row in reversed(rows)
            ]
            
            return messages
        
        except Exception as e:
            logger.error(f"❌ 查询聊天消息失败: {e}", exc_info=True)
            return []
    
    async def get_latest_assistant_message(
        self,
        db: AsyncSession,
        session_id: str
    ) -> Optional[ChatMessage]:
        """
        获取最新的助手消息
        
        Args:
            db: 数据库会话
            session_id: 会话ID
        
        Returns:
            最新的助手消息，如果没有返回 None
        """
        try:
            query = text("""
                SELECT message_id, session_id, role, content, metadata, timestamp as created_at
                FROM chat_messages
                WHERE session_id = :session_id AND role = 'assistant'
                ORDER BY timestamp DESC, message_id DESC
                LIMIT 1
            """)
            
            result = await db.execute(
                query,
                {"session_id": session_id}
            )
            row = result.fetchone()
            
            if row:
                return ChatMessage(
                    message_id=row.message_id,
                    session_id=row.session_id,
                    role=row.role,
                    content=row.content,
                    metadata=row.metadata,
                    created_at=row.created_at
                )
            
            return None
        
        except Exception as e:
            logger.error(f"❌ 查询最新助手消息失败: {e}", exc_info=True)
            return None
