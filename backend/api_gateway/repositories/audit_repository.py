"""
Audit Repository
负责审计日志的数据库操作
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class AuditRepository:
    """审计日志数据访问层"""
    
    @staticmethod
    async def create_audit_log(
        db: AsyncSession,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        changes: Dict[str, Any]
    ) -> None:
        """
        创建审计日志
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            action: 操作类型
            resource_type: 资源类型
            resource_id: 资源ID
            changes: 变更内容
        """
        sql = text("""
            INSERT INTO audit_logs (
                user_id, action, resource_type, resource_id,
                changes, created_at
            ) VALUES (
                :user_id, :action, :resource_type, :resource_id,
                :changes, :created_at
            )
        """)
        
        await db.execute(sql, {
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "changes": json.dumps(changes),
            "created_at": datetime.now()
        })
        
        logger.info(f"✅ 审计日志已记录: {action} - {resource_id}")
