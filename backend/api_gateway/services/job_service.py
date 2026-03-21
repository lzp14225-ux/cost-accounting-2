"""
Job Service
负责任务相关的业务逻辑
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.job_repository import JobRepository
from ..repositories.audit_repository import AuditRepository
from ..repositories.snapshot_repository import SnapshotRepository
from ..repositories.chat_history_repository import ChatHistoryRepository
from ..utils.minio_client import minio_client
from ..utils.rabbitmq_client import rabbitmq_client
from ..utils.validators import validate_dwg_file, validate_prt_file
from ..utils.encryption import process_file_encryption

logger = logging.getLogger(__name__)


class JobService:
    """任务业务逻辑层"""
    
    def __init__(self):
        self.job_repo = JobRepository()
        self.audit_repo = AuditRepository()
        self.snapshot_repo = SnapshotRepository()
        self.chat_history_repo = ChatHistoryRepository()
    
    async def create_job_from_upload(
        self,
        db: AsyncSession,
        user_id: str,
        dwg_file: Optional[UploadFile] = None,
        prt_file: Optional[UploadFile] = None,
        encryption_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        从文件上传创建任务
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            dwg_file: DWG文件
            prt_file: PRT文件
            encryption_key: 加密密钥
        
        Returns:
            任务信息
        """
        logger.info(f"📤 用户 {user_id} 开始创建任务")
        
        # 1. 验证文件
        if not dwg_file and not prt_file:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "NO_FILE_PROVIDED",
                    "message": "至少需要上传一个文件（DWG或PRT）"
                }
            )
        
        if dwg_file:
            await validate_dwg_file(dwg_file)
            logger.info(f"✅ DWG文件验证通过: {dwg_file.filename}")
        
        if prt_file:
            await validate_prt_file(prt_file)
            logger.info(f"✅ PRT文件验证通过: {prt_file.filename}")
        
        # 2. 处理加密（预留）
        if dwg_file:
            dwg_file = await process_file_encryption(dwg_file, encryption_key)
        
        if prt_file:
            prt_file = await process_file_encryption(prt_file, encryption_key)
        
        # 3. 上传文件到MinIO
        dwg_info, prt_info = await self._upload_files(dwg_file, prt_file)
        
        # 4. 生成任务ID
        job_id = str(uuid.uuid4())
        
        # 5. 在数据库事务中创建任务
        try:
            async with db.begin():
                # 5.1 创建任务记录
                await self.job_repo.create_job(
                    db=db,
                    job_id=job_id,
                    user_id=user_id,
                    dwg_info=dwg_info,
                    prt_info=prt_info,
                    dwg_filename=dwg_file.filename if dwg_file else None,
                    prt_filename=prt_file.filename if prt_file else None
                )
                
                # 5.2 创建聊天会话（使用 dwg_file_name 作为会话标题，去掉扩展名）
                session_name = None
                if dwg_file:
                    # 去掉 .dwg 扩展名
                    session_name = dwg_file.filename.rsplit('.', 1)[0] if '.' in dwg_file.filename else dwg_file.filename
                elif prt_file:
                    # 去掉 .prt 扩展名
                    session_name = prt_file.filename.rsplit('.', 1)[0] if '.' in prt_file.filename else prt_file.filename
                
                await self._create_chat_session(
                    db=db,
                    session_id=job_id,
                    job_id=job_id,
                    user_id=user_id,
                    session_name=session_name
                )
                
                # 5.3 创建快照（价格 + 工艺规则）
                snapshot_stats = await self._create_snapshots(db, job_id)
                
                # 5.4 记录审计日志
                await self._create_audit_log(
                    db=db,
                    user_id=user_id,
                    job_id=job_id,
                    dwg_file=dwg_file,
                    prt_file=prt_file,
                    dwg_info=dwg_info,
                    prt_info=prt_info,
                    snapshot_stats=snapshot_stats
                )
            
            logger.info(f"✅ 数据库事务提交成功: {job_id}")
        
        except Exception as e:
            logger.error(f"❌ 数据库写入失败: {e}")
            # 回滚：删除MinIO中的文件
            await self._rollback_files(dwg_info, prt_info)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "DATABASE_ERROR",
                    "message": f"数据库写入失败: {str(e)}"
                }
            )
        
        # 6. 发送消息到RabbitMQ
        await self._publish_job_message(job_id, user_id)
        
        # 7. 返回结果
        logger.info(f"🎉 任务创建完成: {job_id}")
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "文件上传成功，任务已创建，正在处理...",
            "files": {
                "dwg": {
                    "filename": dwg_file.filename if dwg_file else None,
                    "size": dwg_info["file_size"] if dwg_info else None
                },
                "prt": {
                    "filename": prt_file.filename if prt_file else None,
                    "size": prt_info["file_size"] if prt_info else None
                }
            }
        }
    
    async def get_job_status(
        self,
        db: AsyncSession,
        job_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """
        获取任务状态
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            user_id: 用户ID
        
        Returns:
            任务状态信息
        """
        # 查询任务
        job = await self.job_repo.get_job_by_id(db, job_id)
        
        if not job:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "JOB_NOT_FOUND",
                    "message": f"任务不存在: {job_id}"
                }
            )
        
        # 检查权限
        if job.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "PERMISSION_DENIED",
                    "message": "无权访问此任务"
                }
            )
        
        return {
            "job_id": job.job_id,
            "status": job.status,
            "current_stage": job.current_stage,
            "progress": job.progress,
            "files": {
                "dwg": job.dwg_file_name,
                "prt": job.prt_file_name
            },
            "total_cost": float(job.total_cost) if job.total_cost else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None
        }
    
    async def get_price_snapshots(
        self,
        db: AsyncSession,
        job_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """
        获取价格快照
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            user_id: 用户ID
        
        Returns:
            价格快照列表
        """
        # 检查任务权限
        await self._check_job_permission(db, job_id, user_id)
        
        # 查询快照
        snapshots = await self.snapshot_repo.get_price_snapshots(db, job_id)
        
        return {
            "job_id": job_id,
            "count": len(snapshots),
            "snapshots": [
                {
                    "snapshot_id": int(s.snapshot_id),
                    "original_price_id": s.original_price_id,
                    "version_id": s.version_id,
                    "category": s.category,
                    "sub_category": s.sub_category,
                    "description": s.description,
                    "price": s.price,
                    "unit": s.unit,
                    "work_hours": s.work_hours,
                    "min_num": s.min_num,
                    "add_price": s.add_price,
                    "weight_num": s.weight_num,
                    "note": s.note,
                    "instruction": s.instruction,
                    "is_modified": s.is_modified,
                    "modified_at": s.modified_at.isoformat() if s.modified_at else None,
                    "modified_by": s.modified_by,
                    "modification_reason": s.modification_reason,
                    "snapshot_created_at": s.snapshot_created_at.isoformat() if s.snapshot_created_at else None,
                    "metadata": s.metadata
                }
                for s in snapshots
            ]
        }
    
    # 已移除：3表架构不再需要 process_snapshots
    # async def get_process_snapshots(
    #     self,
    #     db: AsyncSession,
    #     job_id: str,
    #     user_id: str
    # ) -> Dict[str, Any]:
    #     """
    #     获取工艺规则快照
    #     
    #     Args:
    #         db: 数据库会话
    #         job_id: 任务ID
    #         user_id: 用户ID
    #     
    #     Returns:
    #         工艺规则快照列表
    #     """
    #     # 检查任务权限
    #     await self._check_job_permission(db, job_id, user_id)
    #     
    #     # 查询快照
    #     snapshots = await self.snapshot_repo.get_process_snapshots(db, job_id)
    #     
    #     return {
    #         "job_id": job_id,
    #         "count": len(snapshots),
    #         "snapshots": [
    #             {
    #                 "snapshot_id": int(s.snapshot_id),
    #                 "original_rule_id": s.original_rule_id,
    #                 "version_id": s.version_id,
    #                 "feature_type": s.feature_type,
    #                 "name": s.name,
    #                 "description": s.description,
    #                 "priority": s.priority,
    #                 "conditions": s.conditions,
    #                 "output_params": s.output_params,
    #                 "is_modified": s.is_modified,
    #                 "modified_at": s.modified_at.isoformat() if s.modified_at else None,
    #                 "modified_by": s.modified_by,
    #                 "modification_reason": s.modification_reason,
    #                 "snapshot_created_at": s.snapshot_created_at.isoformat() if s.snapshot_created_at else None,
    #                 "metadata": s.metadata
    #             }
    #             for s in snapshots
    #         ]
    #     }
    
    # ========== 私有辅助方法 ==========
    
    async def _upload_files(
        self,
        dwg_file: Optional[UploadFile],
        prt_file: Optional[UploadFile]
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        """上传文件到MinIO"""
        dwg_info = None
        prt_info = None
        
        try:
            if dwg_file:
                logger.info(f"📤 开始上传DWG文件: {dwg_file.filename}")
                dwg_info = await minio_client.upload_file(dwg_file, prefix="dwg")
                logger.info(f"✅ DWG文件上传成功: {dwg_info['object_name']}")
            
            if prt_file:
                logger.info(f"📤 开始上传PRT文件: {prt_file.filename}")
                prt_info = await minio_client.upload_file(prt_file, prefix="prt")
                logger.info(f"✅ PRT文件上传成功: {prt_info['object_name']}")
        
        except Exception as e:
            logger.error(f"❌ MinIO上传失败: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "MINIO_UPLOAD_FAILED",
                    "message": f"文件上传失败: {str(e)}"
                }
            )
        
        return dwg_info, prt_info
    
    async def _create_chat_session(
        self,
        db: AsyncSession,
        session_id: str,
        job_id: str,
        user_id: str,
        session_name: Optional[str] = None
    ) -> None:
        """
        创建聊天会话
        
        Args:
            db: 数据库会话
            session_id: 会话ID（与job_id相同）
            job_id: 任务ID
            user_id: 用户ID
            session_name: 会话名称（来自dwg_file_name）
        """
        try:
            await self.chat_history_repo.create_session(
                db_session=db,
                session_id=session_id,
                job_id=job_id,
                user_id=user_id,
                session_name=session_name,
                metadata={
                    "created_from": "file_upload",
                    "file_name": session_name
                }
            )
            logger.info(f"✅ 聊天会话已创建: {session_id}, name={session_name}")
        except Exception as e:
            logger.error(f"❌ 创建聊天会话失败: {e}")
            raise
    
    async def _create_snapshots(self, db: AsyncSession, job_id: str) -> Dict[str, int]:
        """创建快照（仅价格快照）"""
        price_count = await self.snapshot_repo.create_price_snapshots(db, job_id)
        
        result = {
            "price_items_count": price_count
        }
        
        logger.info(f"✅ 快照创建完成: {result}")
        return result
    
    async def _create_audit_log(
        self,
        db: AsyncSession,
        user_id: str,
        job_id: str,
        dwg_file: Optional[UploadFile],
        prt_file: Optional[UploadFile],
        dwg_info: Optional[Dict],
        prt_info: Optional[Dict],
        snapshot_stats: Dict[str, int]
    ) -> None:
        """创建审计日志"""
        changes = {
            "dwg_file": {
                "filename": dwg_file.filename if dwg_file else None,
                "size": dwg_info["file_size"] if dwg_info else None,
                "path": dwg_info["object_name"] if dwg_info else None
            },
            "prt_file": {
                "filename": prt_file.filename if prt_file else None,
                "size": prt_info["file_size"] if prt_info else None,
                "path": prt_info["object_name"] if prt_info else None
            },
            "snapshots": snapshot_stats
        }
        
        await self.audit_repo.create_audit_log(
            db=db,
            user_id=user_id,
            action="file_upload",
            resource_type="job",
            resource_id=job_id,
            changes=changes
        )
    
    async def _rollback_files(
        self,
        dwg_info: Optional[Dict],
        prt_info: Optional[Dict]
    ) -> None:
        """回滚：删除MinIO中的文件"""
        try:
            if dwg_info:
                minio_client.delete_file(dwg_info["object_name"])
                logger.info(f"🔄 已回滚删除DWG文件: {dwg_info['object_name']}")
            
            if prt_info:
                minio_client.delete_file(prt_info["object_name"])
                logger.info(f"🔄 已回滚删除PRT文件: {prt_info['object_name']}")
        except Exception as e:
            logger.error(f"❌ 回滚删除文件失败: {e}")
    
    async def _publish_job_message(self, job_id: str, user_id: str) -> None:
        """发送消息到RabbitMQ"""
        try:
            await rabbitmq_client.publish_job_message(
                job_id=job_id,
                user_id=user_id,
                created_at=datetime.now().isoformat()
            )
            logger.info(f"✅ 消息已发送到RabbitMQ: {job_id}")
        except Exception as e:
            logger.error(f"❌ RabbitMQ消息发送失败: {e}")
            logger.warning(f"⚠️ 任务 {job_id} 已创建但消息发送失败，需要手动重试")
    
    async def _check_job_permission(
        self,
        db: AsyncSession,
        job_id: str,
        user_id: str
    ) -> None:
        """检查任务权限"""
        job = await self.job_repo.get_job_by_id(db, job_id)
        
        if not job:
            raise HTTPException(
                status_code=404,
                detail={"error": "JOB_NOT_FOUND", "message": "任务不存在"}
            )
        
        if job.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail={"error": "PERMISSION_DENIED", "message": "无权访问"}
            )
