"""
任务管理路由 (Controller层)
处理HTTP请求和响应
负责人：ZZH
"""
import logging
import asyncio
import uuid
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import io

from shared.database import get_db
from shared.models import Job
from ..auth import get_current_user
from ..services.job_service import JobService
from ..services.file_service import FileService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _execute_continue_job(orchestrator, job_id: str):
    """Run continue_job in the background so HTTP can return immediately."""
    try:
        logger.info(f"后台继续核算任务开始: job_id={job_id}")
        result = await orchestrator.continue_job(job_id)
        logger.info(f"后台继续核算任务完成: job_id={job_id}, status={result.get('status')}")
    except Exception as e:
        logger.error(f"后台继续核算任务失败: job_id={job_id}, error={e}", exc_info=True)


@router.post("/upload")
async def upload_files(
    dwg_file: Optional[UploadFile] = File(None),
    prt_file: Optional[UploadFile] = File(None),
    encryption_key: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    上传DWG/PRT文件并创建任务
    
    Args:
        dwg_file: DWG文件（可选，但至少要有一个文件）
        prt_file: PRT文件（可选）
        encryption_key: 加密密钥（预留，第一期不使用）
        current_user: 当前用户（从JWT获取）
        db: 数据库会话
    
    Returns:
        {
            "job_id": "uuid",
            "status": "pending",
            "message": "文件上传成功，任务已创建"
        }
    """
    try:
        job_service = JobService()
        
        result = await job_service.create_job_from_upload(
            db=db,
            user_id=current_user["user_id"],
            dwg_file=dwg_file,
            prt_file=prt_file,
            encryption_key=encryption_key
        )
        
        return result
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 文件上传异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"服务器内部错误: {str(e)}"
            }
        )


@router.get("/{job_id}/status")
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    查询任务状态
    
    Args:
        job_id: 任务ID
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        任务状态信息
    """
    try:
        job_service = JobService()
        
        result = await job_service.get_job_status(
            db=db,
            job_id=job_id,
            user_id=current_user["user_id"]
        )
        
        return result
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 查询任务状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": f"查询失败: {str(e)}"
            }
        )


@router.post("/{job_id}/continue")
async def continue_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Continue calculation after the user confirms the review data."""
    try:
        logger.info(f"收到继续核算请求: job_id={job_id}, user_id={current_user['user_id']}")

        try:
            job_uuid = uuid.UUID(job_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail={"message": f"无效的 job_id: {job_id}"})

        result = await db.execute(
            select(Job.status).where(Job.job_id == job_uuid)
        )
        row = result.first()

        if not row:
            raise HTTPException(status_code=404, detail={"message": f"任务不存在: {job_id}"})

        job_status = row[0]
        if job_status != "awaiting_confirm":
            raise HTTPException(
                status_code=400,
                detail={"message": f"任务当前状态为 {job_status}，不能开始核算，期望 awaiting_confirm"}
            )

        from agents import get_orchestrator_agent

        orchestrator = get_orchestrator_agent()
        asyncio.create_task(_execute_continue_job(orchestrator, job_id))

        logger.info(f"继续核算任务已调度: job_id={job_id}")
        return {
            "status": "accepted",
            "message": "任务已开始继续核算，请通过 WebSocket 查看进度",
            "job_id": job_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"继续核算失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"message": f"继续核算失败: {str(e)}"}
        )


@router.get("/{job_id}/snapshots/prices")
async def get_job_price_snapshots(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    查询任务的价格快照
    
    Args:
        job_id: 任务ID
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        价格快照列表
    """
    try:
        job_service = JobService()
        
        result = await job_service.get_price_snapshots(
            db=db,
            job_id=job_id,
            user_id=current_user["user_id"]
        )
        
        return result
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 查询价格快照失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "INTERNAL_SERVER_ERROR", "message": str(e)}
        )


@router.get("/{job_id}/snapshots/processes")
async def get_job_process_snapshots(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    查询任务的工艺规则快照
    
    Args:
        job_id: 任务ID
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        工艺规则快照列表
    """
    try:
        job_service = JobService()
        
        result = await job_service.get_process_snapshots(
            db=db,
            job_id=job_id,
            user_id=current_user["user_id"]
        )
        
        return result
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 查询工艺规则快照失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "INTERNAL_SERVER_ERROR", "message": str(e)}
        )



@router.get("/{job_id}/files/{file_type}/download")
async def download_job_file(
    job_id: str,
    file_type: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    下载任务文件
    
    Args:
        job_id: 任务ID
        file_type: 文件类型 ("dwg" 或 "prt")
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        文件流
    """
    try:
        file_service = FileService()
        
        # 获取文件内容
        file_content = await file_service.get_job_file(
            db=db,
            job_id=job_id,
            file_type=file_type.lower(),
            user_id=current_user["user_id"]
        )
        
        # 确定文件扩展名和MIME类型
        if file_type.lower() == "dwg":
            media_type = "application/acad"
            extension = "dwg"
        elif file_type.lower() == "prt":
            media_type = "application/octet-stream"
            extension = "prt"
        else:
            raise HTTPException(400, detail="Invalid file type")
        
        # 返回文件流
        return Response(
            content=file_content,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={job_id}.{extension}"
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 文件下载失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "DOWNLOAD_FAILED", "message": str(e)}
        )


@router.get("/{job_id}/files/{file_type}/url")
async def get_job_file_url(
    job_id: str,
    file_type: str,
    expires_hours: int = 24,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取任务文件的预签名下载URL
    
    Args:
        job_id: 任务ID
        file_type: 文件类型 ("dwg" 或 "prt")
        expires_hours: URL过期时间（小时，默认24小时）
        current_user: 当前用户
        db: 数据库会话
    
    Returns:
        {
            "url": "预签名URL",
            "expires_in": 86400,
            "file_type": "dwg"
        }
    """
    try:
        file_service = FileService()
        
        url = await file_service.get_job_file_url(
            db=db,
            job_id=job_id,
            file_type=file_type.lower(),
            user_id=current_user["user_id"],
            expires_hours=expires_hours
        )
        
        return {
            "url": url,
            "expires_in": expires_hours * 3600,
            "file_type": file_type.lower()
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ 获取文件URL失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "URL_GENERATION_FAILED", "message": str(e)}
        )
