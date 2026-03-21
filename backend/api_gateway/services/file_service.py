"""
File Service
负责文件下载和访问相关的业务逻辑
"""
import logging
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..utils.minio_client import minio_client
from ..repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)


class FileService:
    """文件业务逻辑层"""
    
    def __init__(self):
        self.job_repo = JobRepository()
    
    async def get_job_file(
        self,
        db: AsyncSession,
        job_id: str,
        file_type: str,  # "dwg" 或 "prt"
        user_id: str
    ) -> bytes:
        """
        获取任务的文件内容
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            file_type: 文件类型 ("dwg" 或 "prt")
            user_id: 用户ID
        
        Returns:
            文件内容（字节流）
        """
        # 1. 查询任务信息
        job = await self.job_repo.get_job_by_id(db, job_id)
        
        if not job:
            raise HTTPException(
                status_code=404,
                detail={"error": "JOB_NOT_FOUND", "message": "任务不存在"}
            )
        
        # 2. 检查权限（统一转换为字符串比较，避免UUID类型不匹配）
        if str(job.user_id) != str(user_id):
            logger.warning(f"❌ 权限检查失败: job.user_id={job.user_id}, user_id={user_id}")
            raise HTTPException(
                status_code=403,
                detail={"error": "PERMISSION_DENIED", "message": "无权访问此文件"}
            )
        
        # 3. 获取文件路径
        if file_type == "dwg":
            file_path = job.dwg_file_path
            file_name = job.dwg_file_name
        elif file_type == "prt":
            file_path = job.prt_file_path
            file_name = job.prt_file_name
        else:
            raise HTTPException(
                status_code=400,
                detail={"error": "INVALID_FILE_TYPE", "message": "文件类型必须是 dwg 或 prt"}
            )
        
        if not file_path:
            raise HTTPException(
                status_code=404,
                detail={"error": "FILE_NOT_FOUND", "message": f"任务中没有 {file_type.upper()} 文件"}
            )
        
        # 4. 从MinIO下载文件
        try:
            logger.info(f"📥 开始下载文件: {file_path}")
            file_content = minio_client.get_file(file_path)
            logger.info(f"✅ 文件下载成功: {file_path} ({len(file_content)} bytes)")
            return file_content
        
        except Exception as e:
            logger.error(f"❌ 文件下载失败: {e}")
            raise HTTPException(
                status_code=500,
                detail={"error": "FILE_DOWNLOAD_FAILED", "message": f"文件下载失败: {str(e)}"}
            )
    
    async def get_job_file_url(
        self,
        db: AsyncSession,
        job_id: str,
        file_type: str,
        user_id: str,
        expires_hours: int = 24
    ) -> str:
        """
        获取任务文件的预签名下载URL
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            file_type: 文件类型 ("dwg" 或 "prt")
            user_id: 用户ID
            expires_hours: URL过期时间（小时）
        
        Returns:
            预签名下载URL
        """
        from datetime import timedelta
        
        # 1. 查询任务信息
        job = await self.job_repo.get_job_by_id(db, job_id)
        
        if not job:
            raise HTTPException(
                status_code=404,
                detail={"error": "JOB_NOT_FOUND", "message": "任务不存在"}
            )
        
        # 2. 检查权限（统一转换为字符串比较，避免UUID类型不匹配）
        if str(job.user_id) != str(user_id):
            logger.warning(f"❌ 权限检查失败: job.user_id={job.user_id}, user_id={user_id}")
            raise HTTPException(
                status_code=403,
                detail={"error": "PERMISSION_DENIED", "message": "无权访问此文件"}
            )
        
        # 3. 获取文件路径
        if file_type == "dwg":
            file_path = job.dwg_file_path
        elif file_type == "prt":
            file_path = job.prt_file_path
        else:
            raise HTTPException(
                status_code=400,
                detail={"error": "INVALID_FILE_TYPE", "message": "文件类型必须是 dwg 或 prt"}
            )
        
        if not file_path:
            raise HTTPException(
                status_code=404,
                detail={"error": "FILE_NOT_FOUND", "message": f"任务中没有 {file_type.upper()} 文件"}
            )
        
        # 4. 生成预签名URL
        try:
            logger.info(f"🔗 生成预签名URL: {file_path}")
            url = minio_client.generate_presigned_url(
                object_name=file_path,
                expires=timedelta(hours=expires_hours)
            )
            logger.info(f"✅ URL生成成功: {file_path}")
            return url
        
        except Exception as e:
            logger.error(f"❌ URL生成失败: {e}")
            raise HTTPException(
                status_code=500,
                detail={"error": "URL_GENERATION_FAILED", "message": f"URL生成失败: {str(e)}"}
            )
    
    async def get_file_by_path(
        self,
        file_path: str
    ) -> bytes:
        """
        直接通过文件路径获取文件（内部使用）
        
        Args:
            file_path: MinIO中的文件路径
        
        Returns:
            文件内容（字节流）
        """
        try:
            logger.info(f"📥 下载文件: {file_path}")
            file_content = minio_client.get_file(file_path)
            logger.info(f"✅ 文件下载成功: {len(file_content)} bytes")
            return file_content
        
        except Exception as e:
            logger.error(f"❌ 文件下载失败: {e}")
            raise Exception(f"文件下载失败: {str(e)}")
