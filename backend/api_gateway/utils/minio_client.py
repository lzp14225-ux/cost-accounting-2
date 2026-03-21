"""
MinIO客户端工具类
处理文件上传、下载、删除等操作
"""
import uuid
from datetime import datetime, timedelta
from typing import BinaryIO, Dict, Optional
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from fastapi import UploadFile
import logging

from ..config import settings

logger = logging.getLogger(__name__)


class MinIOClient:
    """MinIO客户端封装"""
    
    def __init__(self):
        """初始化MinIO客户端"""
        self.client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_USE_HTTPS,
            region=settings.MINIO_REGION
        )
        
        # 如果配置了外部访问地址，创建一个用于生成预签名URL的客户端
        if settings.MINIO_EXTERNAL_ENDPOINT and settings.MINIO_EXTERNAL_ENDPOINT != settings.MINIO_ENDPOINT:
            self.presigned_client = Minio(
                endpoint=settings.MINIO_EXTERNAL_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_USE_HTTPS,
                region=settings.MINIO_REGION
            )
            logger.info(f"✅ MinIO外部访问地址: {settings.MINIO_EXTERNAL_ENDPOINT}")
        else:
            self.presigned_client = self.client
        
        self.bucket_files = settings.MINIO_BUCKET_FILES
        self._ensure_buckets()
    
    def _ensure_buckets(self):
        """确保必要的bucket存在"""
        try:
            if not self.client.bucket_exists(self.bucket_files):
                self.client.make_bucket(self.bucket_files)
                logger.info(f"✅ 创建MinIO bucket: {self.bucket_files}")
        except S3Error as e:
            logger.error(f"❌ 创建MinIO bucket失败: {e}")
            raise
    
    async def upload_file(
        self,
        file: UploadFile,
        prefix: str = "files"
    ) -> Dict[str, str]:
        """
        上传文件到MinIO
        
        Args:
            file: FastAPI UploadFile对象
            prefix: 文件路径前缀（如 "dwg", "prt"）
        
        Returns:
            包含文件信息的字典：
            {
                "file_id": "uuid",
                "object_name": "dwg/2026/01/xxx.dwg",
                "file_size": 12345678,
                "etag": "abc123...",
                "bucket": "files"
            }
        """
        try:
            # 1. 生成唯一文件ID和路径
            file_id = str(uuid.uuid4())
            now = datetime.now()
            file_extension = Path(file.filename).suffix.lower()
            
            # 构造object_name: prefix/year/month/file_id.ext
            object_name = f"{prefix}/{now.year}/{now.month:02d}/{file_id}{file_extension}"
            
            # 2. 获取文件大小
            file.file.seek(0, 2)  # 移动到文件末尾
            file_size = file.file.tell()
            file.file.seek(0)  # 重置到文件开头
            
            # 3. 上传到MinIO（流式上传）
            result = self.client.put_object(
                bucket_name=self.bucket_files,
                object_name=object_name,
                data=file.file,
                length=file_size,
                content_type=file.content_type or "application/octet-stream"
            )
            
            logger.info(f"✅ 文件上传成功: {object_name} ({file_size} bytes)")
            
            # 4. 返回文件信息
            return {
                "file_id": file_id,
                "object_name": object_name,
                "file_path": object_name,  # 别名，方便使用
                "file_size": file_size,
                "etag": result.etag,
                "bucket": self.bucket_files,
                "original_filename": file.filename
            }
        
        except S3Error as e:
            logger.error(f"❌ MinIO上传失败: {e}")
            raise Exception(f"文件上传失败: {str(e)}")
        except Exception as e:
            logger.error(f"❌ 文件上传异常: {e}")
            raise
    
    def get_file(self, object_name: str, bucket: Optional[str] = None) -> bytes:
        """
        从MinIO读取文件
        
        Args:
            object_name: 对象名称/路径
            bucket: bucket名称，默认使用files bucket
        
        Returns:
            文件内容（字节）
        """
        try:
            bucket = bucket or self.bucket_files
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"❌ MinIO读取文件失败: {e}")
            raise Exception(f"文件读取失败: {str(e)}")
    
    def delete_file(self, object_name: str, bucket: Optional[str] = None):
        """
        删除MinIO中的文件
        
        Args:
            object_name: 对象名称/路径
            bucket: bucket名称
        """
        try:
            bucket = bucket or self.bucket_files
            self.client.remove_object(bucket, object_name)
            logger.info(f"✅ 文件删除成功: {object_name}")
        except S3Error as e:
            logger.error(f"❌ MinIO删除文件失败: {e}")
            raise Exception(f"文件删除失败: {str(e)}")
    
    def generate_presigned_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(hours=24),
        bucket: Optional[str] = None
    ) -> str:
        """
        生成预签名下载URL
        
        Args:
            object_name: 对象名称/路径
            expires: 过期时间
            bucket: bucket名称
        
        Returns:
            预签名URL
        """
        try:
            bucket = bucket or self.bucket_files
            # 使用专门的预签名客户端（可能使用外部地址）
            url = self.presigned_client.presigned_get_object(
                bucket_name=bucket,
                object_name=object_name,
                expires=expires
            )
            return url
        except S3Error as e:
            logger.error(f"❌ 生成预签名URL失败: {e}")
            raise Exception(f"生成下载链接失败: {str(e)}")


# 全局MinIO客户端实例
minio_client = MinIOClient()
