"""
Snapshot Repository
负责快照相关的数据库操作
"""
import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SnapshotRepository:
    """快照数据访问层"""
    
    @staticmethod
    async def create_price_snapshots(db: AsyncSession, job_id: str) -> int:
        """
        创建价格快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            创建的快照记录数
        """
        sql = text("""
            INSERT INTO job_price_snapshots (
                job_id, original_price_id, version_id,
                category, sub_category,
                price, unit, work_hours,
                min_num, add_price, weight_num,
                note, instruction, is_modified,
                snapshot_created_at, metadata
            )
            SELECT 
                :job_id,
                id,
                COALESCE(version_id, 'v1.0'),
                category,
                sub_category,
                price,
                unit,
                work_hours,
                min_num,
                add_price,
                weight_num,
                note,
                instruction,
                false,
                NOW(),
                NULL
            FROM price_items
            WHERE is_active = true
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        count = result.rowcount
        
        logger.info(f"✅ 价格快照已创建: job_id={job_id}, count={count}")
        return count
    
    @staticmethod
    async def create_process_snapshots(db: AsyncSession, job_id: str) -> int:
        """
        创建工艺规则快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            创建的快照记录数
        """
        sql = text("""
            INSERT INTO job_process_snapshots (
                job_id, original_rule_id, version_id,
                feature_type, name, description,
                priority, conditions, output_params,
                is_modified, snapshot_created_at, metadata
            )
            SELECT 
                :job_id,
                id,
                COALESCE(version_id, 'v1.0'),
                feature_type,
                name,
                description,
                priority,
                conditions,
                output_params,
                false,
                NOW(),
                NULL
            FROM process_rules
            WHERE is_active = true
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        count = result.rowcount
        
        logger.info(f"✅ 工艺规则快照已创建: job_id={job_id}, count={count}")
        return count
    
    @staticmethod
    async def get_price_snapshots(db: AsyncSession, job_id: str) -> List:
        """
        查询价格快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            价格快照列表
        """
        sql = text("""
            SELECT 
                snapshot_id, job_id, original_price_id, version_id,
                category, sub_category,
                price, unit, work_hours,
                min_num, add_price, weight_num,
                note, instruction,
                is_modified, modified_at, modified_by,
                modification_reason, snapshot_created_at, metadata
            FROM job_price_snapshots
            WHERE job_id = :job_id
            ORDER BY category, sub_category
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchall()
    
    @staticmethod
    async def get_process_snapshots(db: AsyncSession, job_id: str) -> List:
        """
        查询工艺规则快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            工艺规则快照列表
        """
        sql = text("""
            SELECT 
                snapshot_id, job_id, original_rule_id, version_id,
                feature_type, name, description,
                priority, conditions, output_params,
                is_modified, modified_at, modified_by,
                modification_reason, snapshot_created_at, metadata
            FROM job_process_snapshots
            WHERE job_id = :job_id
            ORDER BY feature_type, priority DESC
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchall()
