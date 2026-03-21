"""
交互数据访问层
负责人：ZZH
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime
import uuid
import json
import logging

logger = logging.getLogger(__name__)

class InteractionRepository:
    """交互数据访问层"""
    
    @staticmethod
    async def create_interaction(
        db: AsyncSession,
        job_id: str,
        card_id: str,
        card_type: str,
        card_data: dict
    ) -> str:
        """
        创建交互记录
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            card_id: 卡片ID
            card_type: 卡片类型
            card_data: 卡片数据
            
        Returns:
            interaction_id: 交互记录ID
        """
        interaction_id = str(uuid.uuid4())
        
        sql = text("""
            INSERT INTO user_interactions (
                interaction_id, job_id, card_id, card_type,
                card_data, status, created_at
            ) VALUES (
                :interaction_id, :job_id, :card_id, :card_type,
                :card_data, 'pending', NOW()
            )
        """)
        
        await db.execute(sql, {
            "interaction_id": interaction_id,
            "job_id": job_id,
            "card_id": card_id,
            "card_type": card_type,
            "card_data": json.dumps(card_data)
        })
        
        logger.info(f"✅ 交互记录已创建: interaction_id={interaction_id}, job_id={job_id}")
        
        return interaction_id
    
    @staticmethod
    async def update_interaction_response(
        db: AsyncSession,
        card_id: str,
        action: str,
        user_response: dict
    ):
        """
        更新用户响应
        
        Args:
            db: 数据库会话
            card_id: 卡片ID
            action: 用户操作
            user_response: 用户响应数据
        """
        sql = text("""
            UPDATE user_interactions
            SET user_response = :user_response,
                action = :action,
                status = 'responded',
                responded_at = NOW()
            WHERE card_id = :card_id
        """)
        
        await db.execute(sql, {
            "card_id": card_id,
            "action": action,
            "user_response": json.dumps(user_response)
        })
        
        logger.info(f"✅ 用户响应已更新: card_id={card_id}, action={action}")
    
    @staticmethod
    async def get_pending_interactions(db: AsyncSession, job_id: str):
        """
        获取待处理的交互
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            
        Returns:
            待处理的交互记录列表
        """
        sql = text("""
            SELECT * FROM user_interactions
            WHERE job_id = :job_id AND status = 'pending'
            ORDER BY created_at DESC
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchall()
    
    @staticmethod
    async def get_interaction_by_card_id(db: AsyncSession, card_id: str):
        """
        根据card_id查询交互
        
        Args:
            db: 数据库会话
            card_id: 卡片ID
            
        Returns:
            交互记录
        """
        sql = text("""
            SELECT * FROM user_interactions
            WHERE card_id = :card_id
        """)
        
        result = await db.execute(sql, {"card_id": card_id})
        return result.fetchone()
    
    @staticmethod
    async def get_all_interactions(db: AsyncSession, job_id: str):
        """
        获取任务的所有交互记录
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            
        Returns:
            所有交互记录列表
        """
        sql = text("""
            SELECT * FROM user_interactions
            WHERE job_id = :job_id
            ORDER BY created_at DESC
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchall()
