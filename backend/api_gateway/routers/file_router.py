"""
文件管理路由
负责文件预签名URL生成等文件相关操作
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator
from shared.timezone_utils import now_shanghai

from ..auth import get_current_user
from ..utils.minio_client import minio_client
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/files", tags=["files"])


class PresignedUrlRequest(BaseModel):
    """预签名URL请求模型"""
    file_path: str = Field(..., description="MinIO中的文件路径")
    expires_in: int = Field(..., description="URL过期时间（秒）", ge=60, le=604800)
    bucket_name: Optional[str] = Field(None, description="Bucket名称（可选）")
    download_filename: Optional[str] = Field(None, description="下载时的文件名（可选）")
    
    @validator('file_path')
    def validate_file_path(cls, v):
        """验证文件路径安全性"""
        # 防止路径遍历攻击
        if '..' in v or v.startswith('/') or '\\' in v:
            raise ValueError('文件路径包含非法字符')
        
        # 验证路径不为空
        if not v.strip():
            raise ValueError('文件路径不能为空')
        
        return v.strip()
    
    @validator('expires_in')
    def validate_expires_in(cls, v):
        """验证过期时间范围"""
        if v < 60:
            raise ValueError('过期时间不能少于60秒')
        if v > 604800:  # 7天
            raise ValueError('过期时间不能超过7天（604800秒）')
        return v


class PresignedUrlResponse(BaseModel):
    """预签名URL响应模型"""
    success: bool = True
    data: dict


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def generate_presigned_url(
    request: PresignedUrlRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    生成MinIO文件的临时签名URL
    
    **功能说明:**
    - 为指定的MinIO文件生成临时访问URL
    - 支持自定义过期时间（60秒 - 7天）
    - 需要JWT认证
    - 自动验证文件路径安全性
    
    **请求示例:**
    ```json
    {
        "file_path": "dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-02.dxf",
        "expires_in": 3600
    }
    ```
    
    **响应示例:**
    ```json
    {
        "success": true,
        "data": {
            "url": "http://minio:9000/files/dxf/2026/01/.../LP-02.dxf?X-Amz-Algorithm=...",
            "expires_at": "2026-01-21T13:00:00Z",
            "expires_in": 3600,
            "file_path": "dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-02.dxf"
        }
    }
    ```
    
    Args:
        request: 预签名URL请求参数
        current_user: 当前登录用户（从JWT获取）
    
    Returns:
        包含预签名URL的响应
    
    Raises:
        HTTPException: 文件不存在、权限不足或生成失败时抛出异常
    """
    try:
        # 确定使用的bucket
        bucket_name = request.bucket_name or settings.MINIO_BUCKET_FILES
        
        logger.info(
            f"🔗 生成预签名URL请求 | "
            f"user_id={current_user['user_id']} | "
            f"file_path={request.file_path} | "
            f"expires_in={request.expires_in}s | "
            f"bucket={bucket_name}"
        )
        
        # 检查文件是否存在（可选，根据需求决定是否启用）
        try:
            minio_client.client.stat_object(bucket_name, request.file_path)
        except Exception as e:
            logger.warning(f"⚠️ 文件可能不存在: {request.file_path} | {e}")
            # 注意：这里可以选择抛出异常或继续生成URL
            # 如果文件不存在，URL仍然可以生成，但访问时会404
            # raise HTTPException(
            #     status_code=status.HTTP_404_NOT_FOUND,
            #     detail={
            #         "success": False,
            #         "error": {
            #             "code": "FILE_NOT_FOUND",
            #             "message": "文件不存在"
            #         }
            #     }
            # )
        
        # 生成预签名URL
        expires_delta = timedelta(seconds=request.expires_in)
        
        # 构建响应头参数（如果需要自定义下载文件名）
        response_headers = {}
        if request.download_filename:
            response_headers['response-content-disposition'] = (
                f'attachment; filename="{request.download_filename}"'
            )
        
        # 生成URL
        if response_headers:
            # 如果有自定义响应头，使用带参数的方法
            url = minio_client.presigned_client.presigned_get_object(
                bucket_name=bucket_name,
                object_name=request.file_path,
                expires=expires_delta,
                response_headers=response_headers
            )
        else:
            # 标准生成方法（会自动使用外部地址）
            url = minio_client.generate_presigned_url(
                object_name=request.file_path,
                expires=expires_delta,
                bucket=bucket_name
            )
        
        # 计算过期时间
        expires_at = now_shanghai() + expires_delta
        
        logger.info(
            f"✅ 预签名URL生成成功 | "
            f"user_id={current_user['user_id']} | "
            f"file_path={request.file_path} | "
            f"expires_at={expires_at.isoformat()}Z"
        )
        
        return {
            "success": True,
            "data": {
                "url": url,
                "expires_at": expires_at.isoformat() + "Z",
                "expires_in": request.expires_in,
                "file_path": request.file_path,
                "bucket": bucket_name
            }
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(
            f"❌ 生成预签名URL失败 | "
            f"user_id={current_user['user_id']} | "
            f"file_path={request.file_path} | "
            f"error={str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": {
                    "code": "URL_GENERATION_FAILED",
                    "message": f"生成预签名URL失败: {str(e)}"
                }
            }
        )
