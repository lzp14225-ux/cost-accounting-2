"""
快照管理工具
负责创建和管理价格快照、工艺规则快照
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SnapshotManager:
    """快照管理器"""
    
    @staticmethod
    async def create_price_snapshot(db: AsyncSession, job_id: str) -> int:
        """
        创建价格快照
        将price_items表中的所有有效记录复制到job_price_snapshots表
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            创建的快照记录数
        """
        try:
            sql = text("""
                INSERT INTO job_price_snapshots (
                    snapshot_id, job_id, original_price_id,
                    feature_type, name, description,
                    unit_price, unit, param_conditions,
                    priority, is_modified, created_at
                )
                SELECT 
                    gen_random_uuid(),
                    :job_id,
                    id,
                    feature_type, name, description,
                    unit_price, unit, param_conditions,
                    priority, false, NOW()
                FROM price_items
                WHERE is_deleted = false
            """)
            
            result = await db.execute(sql, {"job_id": job_id})
            count = result.rowcount
            
            logger.info(f"✅ 价格快照已创建: job_id={job_id}, count={count}")
            return count
        
        except Exception as e:
            logger.error(f"❌ 创建价格快照失败: {e}")
            raise
    
    @staticmethod
    async def create_process_snapshot(db: AsyncSession, job_id: str) -> int:
        """
        创建工艺规则快照
        将process_rules表中的所有有效记录复制到job_process_snapshots表
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            创建的快照记录数
        """
        try:
            sql = text("""
                INSERT INTO job_process_snapshots (
                    snapshot_id, job_id, original_rule_id,
                    feature_type, name, description,
                    conditions, output_params,
                    priority, is_modified, created_at
                )
                SELECT 
                    gen_random_uuid(),
                    :job_id,
                    id,
                    feature_type, name, description,
                    conditions, output_params,
                    priority, false, NOW()
                FROM process_rules
                WHERE is_deleted = false
            """)
            
            result = await db.execute(sql, {"job_id": job_id})
            count = result.rowcount
            
            logger.info(f"✅ 工艺规则快照已创建: job_id={job_id}, count={count}")
            return count
        
        except Exception as e:
            logger.error(f"❌ 创建工艺规则快照失败: {e}")
            raise
    
    @staticmethod
    async def create_all_snapshots(db: AsyncSession, job_id: str) -> Dict[str, int]:
        """
        创建所有快照（价格 + 工艺规则）
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            快照统计信息
        """
        logger.info(f"📸 开始创建快照: job_id={job_id}")
        
        # 创建价格快照
        price_count = await SnapshotManager.create_price_snapshot(db, job_id)
        
        # 创建工艺规则快照
        process_count = await SnapshotManager.create_process_snapshot(db, job_id)
        
        result = {
            "price_items_count": price_count,
            "process_rules_count": process_count,
            "total_count": price_count + process_count
        }
        
        logger.info(f"✅ 所有快照创建完成: {result}")
        return result
    
    @staticmethod
    async def get_price_snapshots(db: AsyncSession, job_id: str) -> list:
        """
        查询任务的价格快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            价格快照列表
        """
        sql = text("""
            SELECT 
                snapshot_id, job_id, original_price_id,
                feature_type, name, description,
                unit_price, unit, param_conditions,
                priority, is_modified, modified_at, modified_by,
                created_at
            FROM job_price_snapshots
            WHERE job_id = :job_id
            ORDER BY feature_type, priority DESC
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchall()
    
    @staticmethod
    async def get_process_snapshots(db: AsyncSession, job_id: str) -> list:
        """
        查询任务的工艺规则快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            工艺规则快照列表
        """
        sql = text("""
            SELECT 
                snapshot_id, job_id, original_rule_id,
                feature_type, name, description,
                conditions, output_params,
                priority, is_modified, modified_at, modified_by,
                created_at
            FROM job_process_snapshots
            WHERE job_id = :job_id
            ORDER BY feature_type, priority DESC
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchall()
    
    @staticmethod
    async def update_price_snapshot(
        db: AsyncSession,
        snapshot_id: str,
        unit_price: float,
        modified_by: str
    ):
        """
        更新价格快照（用户修改）
        
        Args:
            db: 数据库会话
            snapshot_id: 快照ID
            unit_price: 新单价
            modified_by: 修改人
        """
        sql = text("""
            UPDATE job_price_snapshots
            SET 
                unit_price = :unit_price,
                is_modified = true,
                modified_at = NOW(),
                modified_by = :modified_by
            WHERE snapshot_id = :snapshot_id
        """)
        
        await db.execute(sql, {
            "snapshot_id": snapshot_id,
            "unit_price": unit_price,
            "modified_by": modified_by
        })
        
        logger.info(f"✅ 价格快照已更新: snapshot_id={snapshot_id}")
    
    @staticmethod
    async def update_process_snapshot(
        db: AsyncSession,
        snapshot_id: str,
        conditions: Dict[str, Any],
        output_params: Dict[str, Any],
        modified_by: str
    ):
        """
        更新工艺规则快照（用户修改）
        
        Args:
            db: 数据库会话
            snapshot_id: 快照ID
            conditions: 新条件
            output_params: 新输出参数
            modified_by: 修改人
        """
        sql = text("""
            UPDATE job_process_snapshots
            SET 
                conditions = :conditions,
                output_params = :output_params,
                is_modified = true,
                modified_at = NOW(),
                modified_by = :modified_by
            WHERE snapshot_id = :snapshot_id
        """)
        
        await db.execute(sql, {
            "snapshot_id": snapshot_id,
            "conditions": conditions,
            "output_params": output_params,
            "modified_by": modified_by
        })
        
        logger.info(f"✅ 工艺规则快照已更新: snapshot_id={snapshot_id}")


# 便捷函数
async def create_snapshots_for_job(db: AsyncSession, job_id: str) -> Dict[str, int]:
    """
    为任务创建快照（便捷函数）
    
    Args:
        db: 数据库会话
        job_id: 任务ID
    
    Returns:
        快照统计信息
    """
    return await SnapshotManager.create_all_snapshots(db, job_id)
