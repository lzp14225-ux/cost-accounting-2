"""
Job Repository
负责任务相关的数据库操作
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from shared.timezone_utils import now_shanghai

logger = logging.getLogger(__name__)


class JobRepository:
    """任务数据访问层"""
    
    @staticmethod
    async def create_job(
        db: AsyncSession,
        job_id: str,
        user_id: str,
        dwg_info: Optional[Dict[str, Any]] = None,
        prt_info: Optional[Dict[str, Any]] = None,
        dwg_filename: Optional[str] = None,
        prt_filename: Optional[str] = None
    ) -> None:
        """
        创建任务记录
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            user_id: 用户ID
            dwg_info: DWG文件信息
            prt_info: PRT文件信息
            dwg_filename: DWG原始文件名
            prt_filename: PRT原始文件名
        """
        sql = text("""
            INSERT INTO jobs (
                job_id, user_id,
                dwg_file_id, dwg_file_name, dwg_file_path, dwg_file_size,
                prt_file_id, prt_file_name, prt_file_path, prt_file_size,
                status, current_stage, progress, created_at, updated_at
            ) VALUES (
                :job_id, :user_id,
                :dwg_file_id, :dwg_file_name, :dwg_file_path, :dwg_file_size,
                :prt_file_id, :prt_file_name, :prt_file_path, :prt_file_size,
                :status, :current_stage, :progress, :created_at, :updated_at
            )
        """)
        
        await db.execute(sql, {
            "job_id": job_id,
            "user_id": user_id,
            "dwg_file_id": dwg_info["file_id"] if dwg_info else None,
            "dwg_file_name": dwg_filename,
            "dwg_file_path": dwg_info["object_name"] if dwg_info else None,
            "dwg_file_size": dwg_info["file_size"] if dwg_info else None,
            "prt_file_id": prt_info["file_id"] if prt_info else None,
            "prt_file_name": prt_filename,
            "prt_file_path": prt_info["object_name"] if prt_info else None,
            "prt_file_size": prt_info["file_size"] if prt_info else None,
            "status": "pending",
            "current_stage": "initializing",
            "progress": 0,
            "created_at": now_shanghai(),
            "updated_at": now_shanghai()
        })
        
        logger.info(f"✅ Job记录已创建: {job_id}")
    
    @staticmethod
    async def get_job_by_id(db: AsyncSession, job_id: str):
        """
        根据ID查询任务
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            任务记录或None
        """
        sql = text("""
            SELECT 
                job_id, user_id, status, current_stage, progress,
                dwg_file_id, dwg_file_name, dwg_file_path, dwg_file_size,
                prt_file_id, prt_file_name, prt_file_path, prt_file_size,
                total_cost, created_at, updated_at, completed_at
            FROM jobs
            WHERE job_id = :job_id
        """)
        
        result = await db.execute(sql, {"job_id": job_id})
        return result.fetchone()
    
    @staticmethod
    async def update_job_status(
        db: AsyncSession,
        job_id: str,
        status: str,
        current_stage: Optional[str] = None,
        progress: Optional[int] = None
    ) -> None:
        """
        更新任务状态
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            status: 新状态
            current_stage: 当前阶段
            progress: 进度
        """
        sql = text("""
            UPDATE jobs
            SET status = :status,
                current_stage = COALESCE(:current_stage, current_stage),
                progress = COALESCE(:progress, progress),
                updated_at = :updated_at
            WHERE job_id = :job_id
        """)
        
        await db.execute(sql, {
            "job_id": job_id,
            "status": status,
            "current_stage": current_stage,
            "progress": progress,
            "updated_at": now_shanghai()
        })
        
        logger.info(f"✅ Job状态已更新: {job_id} -> {status}")
