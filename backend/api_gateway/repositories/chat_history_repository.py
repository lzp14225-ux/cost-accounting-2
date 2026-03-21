"""
聊天历史数据访问层
负责人：人员B2

职责:
1. 创建和管理聊天会话
2. 保存和查询聊天消息
3. 获取会话历史
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import json
from sqlalchemy import text
from shared.timezone_utils import now_shanghai

logger = logging.getLogger(__name__)


def json_serializer(obj):
    """
    自定义 JSON 序列化器，处理 datetime 对象
    
    Args:
        obj: 要序列化的对象
    
    Returns:
        序列化后的字符串（对于 datetime）
    
    Raises:
        TypeError: 如果对象类型不支持序列化
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class ChatHistoryRepository:
    """聊天历史数据访问层"""
    
    async def create_session(
        self,
        db_session,
        session_id: str,
        job_id: str,
        user_id: str,
        session_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        创建聊天会话
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
            job_id: 任务ID
            user_id: 用户ID
            session_name: 会话名称（通常是文件名）
            metadata: 额外信息（如文件名等）
        
        Returns:
            会话信息
        """
        try:
            query = text("""
                INSERT INTO chat_sessions (session_id, job_id, user_id, name, metadata, created_at, updated_at)
                VALUES (:session_id, :job_id, :user_id, :name, :metadata, :created_at, :updated_at)
                ON CONFLICT (session_id) DO UPDATE
                SET updated_at = :updated_at,
                    name = COALESCE(EXCLUDED.name, chat_sessions.name)
                RETURNING session_id, job_id, user_id, name, created_at, status
            """)
            
            current_time = now_shanghai()
            
            result = await db_session.execute(
                query,
                {
                    "session_id": session_id,
                    "job_id": job_id,
                    "user_id": user_id,
                    "name": session_name,
                    "metadata": json.dumps(metadata or {}, default=json_serializer),
                    "created_at": current_time,
                    "updated_at": current_time
                }
            )
            
            row = result.fetchone()
            
            return {
                "session_id": row[0],
                "job_id": row[1],
                "user_id": row[2],
                "name": row[3],
                "created_at": row[4].isoformat(),
                "status": row[5]
            }
        
        except Exception as e:
            logger.error(f"创建会话失败: {e}", exc_info=True)
            raise
    
    async def add_message(
        self,
        db_session,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        添加聊天消息
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
            role: 消息角色（user, assistant, system）
            content: 消息内容
            metadata: 额外信息
        
        Returns:
            消息信息
        """
        try:
            query = text("""
                INSERT INTO chat_messages (session_id, role, content, metadata, timestamp)
                VALUES (:session_id, :role, :content, :metadata, :timestamp)
                RETURNING message_id, session_id, role, content, timestamp
            """)
            
            result = await db_session.execute(
                query,
                {
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "metadata": json.dumps(metadata or {}, default=json_serializer),
                    "timestamp": now_shanghai()
                }
            )
            
            row = result.fetchone()
            
            return {
                "message_id": row[0],
                "session_id": row[1],
                "role": row[2],
                "content": row[3],
                "timestamp": row[4].isoformat()
            }
        
        except Exception as e:
            logger.error(f"添加消息失败: {e}", exc_info=True)
            raise
    
    async def get_session_history(
        self,
        db_session,
        session_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        获取会话历史消息
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
            limit: 返回消息数量限制
            offset: 偏移量，从第几条记录开始返回
        
        Returns:
            消息列表
        """
        try:
            query = text("""
                SELECT message_id, role, content, timestamp, metadata
                FROM chat_messages
                WHERE session_id = :session_id
                ORDER BY timestamp ASC, message_id ASC
                LIMIT :limit
                OFFSET :offset
            """)
            
            result = await db_session.execute(
                query,
                {"session_id": session_id, "limit": limit, "offset": offset}
            )
            
            messages = []
            for row in result.fetchall():
                messages.append({
                    "message_id": row[0],
                    "role": row[1],
                    "content": row[2],
                    "timestamp": row[3].isoformat(),
                    "metadata": row[4] or {}
                })
            
            return messages
        
        except Exception as e:
            logger.error(f"获取会话历史失败: {e}", exc_info=True)
            raise
    
    async def get_recent_session_history(
        self,
        db_session,
        session_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        获取会话的最近N条消息（用于上下文推断）
        
        与 get_session_history 的区别：
        - get_session_history: 从最早的消息开始获取（用于分页API）
        - get_recent_session_history: 获取最近的N条消息（用于意图识别和历史推断）
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
            limit: 返回消息数量限制（默认50）
        
        Returns:
            消息列表（按时间从旧到新排序）
        """
        try:
            # 使用子查询获取最近的N条消息，然后按时间升序排列
            query = text("""
                SELECT message_id, role, content, timestamp, metadata
                FROM (
                    SELECT message_id, role, content, timestamp, metadata
                    FROM chat_messages
                    WHERE session_id = :session_id
                    ORDER BY timestamp DESC, message_id DESC
                    LIMIT :limit
                ) AS recent_messages
                ORDER BY timestamp ASC, message_id ASC
            """)
            
            result = await db_session.execute(
                query,
                {"session_id": session_id, "limit": limit}
            )
            
            messages = []
            for row in result.fetchall():
                messages.append({
                    "message_id": row[0],
                    "role": row[1],
                    "content": row[2],
                    "timestamp": row[3].isoformat(),
                    "metadata": row[4] or {}
                })
            
            return messages
        
        except Exception as e:
            logger.error(f"获取最近会话历史失败: {e}", exc_info=True)
            raise
    
    async def get_session_message_count(
        self,
        db_session,
        session_id: str
    ) -> int:
        """
        获取会话的总消息数
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
        
        Returns:
            消息总数
        """
        try:
            query = text("""
                SELECT COUNT(*) as total
                FROM chat_messages
                WHERE session_id = :session_id
            """)
            
            result = await db_session.execute(
                query,
                {"session_id": session_id}
            )
            
            row = result.fetchone()
            return row[0] if row else 0
        
        except Exception as e:
            logger.error(f"获取会话消息总数失败: {e}", exc_info=True)
            raise
    
    async def get_session_info(
        self,
        db_session,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取会话信息
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
        
        Returns:
            会话信息，如果不存在返回 None
        """
        try:
            query = text("""
                SELECT session_id, job_id, user_id, name, created_at, updated_at, status, metadata
                FROM chat_sessions
                WHERE session_id = :session_id
            """)
            
            result = await db_session.execute(
                query,
                {"session_id": session_id}
            )
            
            row = result.fetchone()
            
            if not row:
                return None
            
            return {
                "session_id": row[0],
                "job_id": row[1],
                "user_id": row[2],
                "name": row[3],
                "created_at": row[4].isoformat(),
                "updated_at": row[5].isoformat(),
                "status": row[6],
                "metadata": row[7] or {}
            }
        
        except Exception as e:
            logger.error(f"获取会话信息失败: {e}", exc_info=True)
            raise
    
    async def get_user_sessions(
        self,
        db_session,
        user_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取用户的所有会话
        
        Args:
            db_session: 数据库会话
            user_id: 用户ID
            limit: 返回会话数量限制
        
        Returns:
            会话列表
        """
        try:
            query = text("""
                SELECT s.session_id, s.job_id, s.name, s.created_at, s.updated_at, s.status, s.metadata,
                       COUNT(m.message_id) as message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON s.session_id = m.session_id
                WHERE s.user_id = :user_id
                GROUP BY s.session_id, s.job_id, s.name, s.created_at, s.updated_at, s.status, s.metadata
                ORDER BY s.updated_at DESC
                LIMIT :limit
            """)
            
            result = await db_session.execute(
                query,
                {"user_id": user_id, "limit": limit}
            )
            
            sessions = []
            for row in result.fetchall():
                sessions.append({
                    "session_id": row[0],
                    "job_id": row[1],
                    "name": row[2],
                    "created_at": row[3].isoformat(),
                    "updated_at": row[4].isoformat(),
                    "status": row[5],
                    "metadata": row[6] or {},
                    "message_count": row[7]
                })
            
            return sessions
        
        except Exception as e:
            logger.error(f"获取用户会话列表失败: {e}", exc_info=True)
            raise
    
    async def archive_session(
        self,
        db_session,
        session_id: str
    ) -> bool:
        """
        归档会话
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
        
        Returns:
            是否成功
        """
        try:
            query = text("""
                UPDATE chat_sessions
                SET status = 'archived', updated_at = :updated_at
                WHERE session_id = :session_id
            """)
            
            await db_session.execute(query, {
                "session_id": session_id,
                "updated_at": now_shanghai()
            })
            
            return True
        
        except Exception as e:
            logger.error(f"归档会话失败: {e}", exc_info=True)
            return False
