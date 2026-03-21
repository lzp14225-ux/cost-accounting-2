"""
文件验证工具
检查文件类型、大小等
"""
import logging
from pathlib import Path
from typing import Optional
from fastapi import UploadFile, HTTPException

from ..config import settings

logger = logging.getLogger(__name__)


class FileValidator:
    """文件验证器"""
    
    @staticmethod
    def validate_file_extension(filename: str) -> bool:
        """
        验证文件扩展名
        
        Args:
            filename: 文件名
        
        Returns:
            是否合法
        """
        extension = Path(filename).suffix.lower()
        allowed = settings.ALLOWED_EXTENSIONS_LIST
        
        if extension not in allowed:
            logger.warning(f"❌ 不支持的文件类型: {extension}, 允许的类型: {allowed}")
            return False
        
        return True
    
    @staticmethod
    async def validate_file_size(file: UploadFile) -> bool:
        """
        验证文件大小
        
        Args:
            file: 上传的文件
        
        Returns:
            是否合法
        """
        # 获取文件大小
        file.file.seek(0, 2)  # 移动到文件末尾
        file_size = file.file.tell()
        file.file.seek(0)  # 重置到文件开头
        
        max_size = settings.MAX_FILE_SIZE_BYTES
        
        if file_size > max_size:
            logger.warning(
                f"❌ 文件过大: {file_size} bytes, "
                f"最大允许: {max_size} bytes ({settings.MAX_FILE_SIZE_MB}MB)"
            )
            return False
        
        if file_size == 0:
            logger.warning("❌ 文件为空")
            return False
        
        return True
    
    @staticmethod
    def validate_mime_type(file: UploadFile) -> bool:
        """
        验证MIME类型（宽松检查）
        
        Args:
            file: 上传的文件
        
        Returns:
            是否合法
        """
        extension = Path(file.filename).suffix.lower()
        content_type = file.content_type or ""
        
        # DWG文件的MIME类型
        dwg_mimes = [
            "application/acad",
            "application/x-acad",
            "image/vnd.dwg",
            "application/dwg",
            "application/x-dwg",
            "application/octet-stream"  # 通用二进制
        ]
        
        # PRT文件的MIME类型
        prt_mimes = [
            "application/x-prt",
            "model/prt",
            "application/prt",
            "application/octet-stream"  # 通用二进制
        ]
        
        # 根据扩展名检查MIME类型
        if extension == ".dwg":
            if content_type and content_type not in dwg_mimes:
                logger.warning(f"⚠️ DWG文件MIME类型异常: {content_type}，但允许继续")
            return True
        
        elif extension == ".prt":
            if content_type and content_type not in prt_mimes:
                logger.warning(f"⚠️ PRT文件MIME类型异常: {content_type}，但允许继续")
            return True
        
        return True
    
    @staticmethod
    async def validate_file(file: Optional[UploadFile], file_type: str = "文件") -> None:
        """
        完整的文件验证
        
        Args:
            file: 上传的文件
            file_type: 文件类型描述（用于错误提示）
        
        Raises:
            HTTPException: 验证失败时抛出
        """
        if not file:
            return
        
        # 1. 验证文件扩展名
        if not FileValidator.validate_file_extension(file.filename):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_FILE_TYPE",
                    "message": f"{file_type}格式不支持",
                    "allowed_extensions": settings.ALLOWED_EXTENSIONS_LIST
                }
            )
        
        # 2. 验证文件大小
        if not await FileValidator.validate_file_size(file):
            file.file.seek(0, 2)
            actual_size = file.file.tell()
            file.file.seek(0)
            
            raise HTTPException(
                status_code=413,
                detail={
                    "error": "FILE_TOO_LARGE",
                    "message": f"{file_type}大小超过限制",
                    "max_size_mb": settings.MAX_FILE_SIZE_MB,
                    "actual_size_bytes": actual_size
                }
            )
        
        # 3. 验证MIME类型（宽松检查）
        FileValidator.validate_mime_type(file)
        
        logger.info(f"✅ {file_type}验证通过: {file.filename}")


# 便捷函数
async def validate_dwg_file(file: Optional[UploadFile]):
    """验证DWG文件"""
    await FileValidator.validate_file(file, "DWG文件")


async def validate_prt_file(file: Optional[UploadFile]):
    """验证PRT文件"""
    await FileValidator.validate_file(file, "PRT文件")
