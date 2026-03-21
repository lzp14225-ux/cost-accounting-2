# -*- coding: utf-8 -*-
"""
MinIO 客户端工具类
用于从 MinIO 对象存储中获取文件
"""

from minio import Minio
from minio.error import S3Error
from loguru import logger
import os
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple
import time

# 加载环境变量
load_dotenv()


class MinIOClient:
    """MinIO 客户端封装类"""
    
    def __init__(self):
        """初始化 MinIO 客户端"""
        self.endpoint = os.getenv('MINIO_ENDPOINT')
        self.access_key = os.getenv('MINIO_ACCESS_KEY')
        self.secret_key = os.getenv('MINIO_SECRET_KEY')
        self.region = os.getenv('MINIO_REGION')
        self.use_https = os.getenv('MINIO_USE_HTTPS').lower() == 'true'
        self.bucket_files = os.getenv('MINIO_BUCKET_FILES')
        
        # 上传性能配置
        self.upload_part_size = int(os.getenv('MINIO_UPLOAD_PART_SIZE', str(10 * 1024 * 1024)))  # 默认 10MB
        self.upload_workers = int(os.getenv('MINIO_UPLOAD_WORKERS', '5'))  # 默认 5 个并发上传
        
        try:
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.use_https,
                region=self.region
            )
            logger.info(f"✅ MinIO 客户端初始化成功: {self.endpoint}")
            logger.info(f"📊 上传配置: 分片大小={self.upload_part_size / 1024 / 1024:.1f}MB, 并发数={self.upload_workers}")
        except Exception as e:
            logger.error(f"❌ MinIO 客户端初始化失败: {e}")
            self.client = None
    
    def get_file(self, file_path: str, save_path: str) -> bool:
        """
        从 MinIO 获取文件并保存到本地
        
        Args:
            file_path: MinIO 中的文件路径（对象名称）
            save_path: 本地保存路径
        
        Returns:
            成功返回 True，失败返回 False
        """
        if not self.client:
            logger.error("MinIO 客户端未初始化")
            return False
        
        try:
            # 确保保存目录存在
            save_dir = Path(save_path).parent
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # 从 MinIO 下载文件
            logger.info(f"从 MinIO 下载文件: bucket={self.bucket_files}, path={file_path}")
            self.client.fget_object(
                bucket_name=self.bucket_files,
                object_name=file_path,
                file_path=save_path
            )
            
            logger.info(f"✅ 文件下载成功: {save_path}")
            return True
            
        except S3Error as e:
            logger.error(f"❌ MinIO 下载失败 (S3Error): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ MinIO 下载失败: {e}")
            return False
    
    def upload_file(self, local_path: str, minio_path: str, show_progress: bool = False) -> bool:
        """
        上传文件到 MinIO（支持分片上传优化）
        
        Args:
            local_path: 本地文件路径
            minio_path: MinIO 中的目标路径（对象名称）
            show_progress: 是否显示上传进度（默认 False）
        
        Returns:
            成功返回 True，失败返回 False
        """
        if not self.client:
            logger.error("MinIO 客户端未初始化")
            return False
        
        try:
            # 检查本地文件是否存在
            if not os.path.exists(local_path):
                logger.error(f"本地文件不存在: {local_path}")
                return False
            
            # 获取文件大小
            file_size = os.path.getsize(local_path)
            file_size_mb = file_size / 1024 / 1024
            
            start_time = time.time()
            
            # 上传文件到 MinIO（使用分片上传优化）
            self.client.fput_object(
                bucket_name=self.bucket_files,
                object_name=minio_path,
                file_path=local_path,
                part_size=self.upload_part_size  # 使用配置的分片大小
            )
            
            upload_time = time.time() - start_time
            upload_speed = file_size_mb / upload_time if upload_time > 0 else 0
            
            if show_progress:
                logger.info(f"✅ 上传成功: {minio_path} ({file_size_mb:.2f}MB, {upload_time:.2f}s, {upload_speed:.2f}MB/s)")
            
            return True
            
        except S3Error as e:
            logger.error(f"❌ MinIO 上传失败 (S3Error): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ MinIO 上传失败: {e}")
            return False
    
    def file_exists(self, file_path: str) -> bool:
        """
        检查文件是否存在于 MinIO
        
        Args:
            file_path: MinIO 中的文件路径（对象名称）
        
        Returns:
            存在返回 True，不存在返回 False
        """
        if not self.client:
            return False
        
        try:
            self.client.stat_object(
                bucket_name=self.bucket_files,
                object_name=file_path
            )
            return True
        except S3Error:
            return False
        except Exception as e:
            logger.error(f"检查文件存在性失败: {e}")
            return False
    
    def _download_single_file(self, file_info: Tuple[str, str, str]) -> Dict:
        """
        下载单个文件（用于并行下载）
        
        Args:
            file_info: (file_id, minio_path, save_path) 元组
        
        Returns:
            下载结果字典
        """
        file_id, minio_path, save_path = file_info
        start_time = time.time()
        
        try:
            success = self.get_file(minio_path, save_path)
            download_time = time.time() - start_time
            
            if success:
                file_size = Path(save_path).stat().st_size / 1024 / 1024  # MB
                return {
                    'file_id': file_id,
                    'success': True,
                    'save_path': save_path,
                    'download_time': download_time,
                    'file_size': file_size
                }
            else:
                return {
                    'file_id': file_id,
                    'success': False,
                    'error': '下载失败',
                    'download_time': download_time
                }
        except Exception as e:
            download_time = time.time() - start_time
            return {
                'file_id': file_id,
                'success': False,
                'error': str(e),
                'download_time': download_time
            }
    
    def _upload_single_file(self, file_info: Tuple[str, str, str]) -> Dict:
        """
        上传单个文件（用于并行上传）
        
        Args:
            file_info: (file_id, local_path, minio_path) 元组
        
        Returns:
            上传结果字典
        """
        file_id, local_path, minio_path = file_info
        start_time = time.time()
        
        try:
            # 获取文件大小
            file_size = os.path.getsize(local_path) / 1024 / 1024  # MB
            
            success = self.upload_file(local_path, minio_path, show_progress=False)
            upload_time = time.time() - start_time
            
            if success:
                upload_speed = file_size / upload_time if upload_time > 0 else 0
                return {
                    'file_id': file_id,
                    'success': True,
                    'minio_path': minio_path,
                    'upload_time': upload_time,
                    'file_size': file_size,
                    'upload_speed': upload_speed
                }
            else:
                return {
                    'file_id': file_id,
                    'success': False,
                    'error': '上传失败',
                    'upload_time': upload_time
                }
        except Exception as e:
            upload_time = time.time() - start_time
            return {
                'file_id': file_id,
                'success': False,
                'error': str(e),
                'upload_time': upload_time
            }
    
    def batch_upload_files(
        self, 
        file_list: List[Tuple[str, str, str]], 
        max_workers: int = None
    ) -> Dict[str, Dict]:
        """
        并行批量上传文件
        
        Args:
            file_list: 文件列表，每个元素为 (file_id, local_path, minio_path) 元组
            max_workers: 最大并发数，默认使用配置的 upload_workers
        
        Returns:
            上传结果字典，key 为 file_id，value 为上传结果
            
        Example:
            file_list = [
                ('file1', '/tmp/file1.dxf', 'dxf/2026/01/xxx/file1.dxf'),
                ('file2', '/tmp/file2.dxf', 'dxf/2026/01/xxx/file2.dxf'),
            ]
            results = minio_client.batch_upload_files(file_list, max_workers=5)
        """
        if not self.client:
            logger.error("MinIO 客户端未初始化")
            return {}
        
        if not file_list:
            logger.warning("文件列表为空")
            return {}
        
        # 使用配置的并发数
        if max_workers is None:
            max_workers = self.upload_workers
        
        total_files = len(file_list)
        
        start_time = time.time()
        results = {}
        success_count = 0
        failed_count = 0
        total_size = 0
        
        # 使用线程池并行上传
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有上传任务
            future_to_file = {
                executor.submit(self._upload_single_file, file_info): file_info[0]
                for file_info in file_list
            }
            
            # 收集结果（支持 Ctrl+C 中断）
            try:
                for future in as_completed(future_to_file):
                    file_id = future_to_file[future]
                    try:
                        result = future.result(timeout=300)  # 设置超时
                        results[file_id] = result
                        
                        if result['success']:
                            success_count += 1
                            total_size += result.get('file_size', 0)
                            # 每10个文件打印一次进度
                            if success_count % 10 == 0:
                                logger.info(
                                    f"✅ [{success_count}/{total_files}] 已上传 {success_count} 个文件"
                                )
                        else:
                            failed_count += 1
                            logger.error(
                                f"❌ 上传失败: {file_id} - {result.get('error', '未知错误')}"
                            )
                            
                    except Exception as e:
                        failed_count += 1
                        results[file_id] = {
                            'file_id': file_id,
                            'success': False,
                            'error': str(e)
                        }
                        logger.error(f"❌ {file_id} 上传异常: {e}")
                        
            except KeyboardInterrupt:
                logger.warning("⚠️ 收到中断信号，正在取消上传任务...")
                # 取消所有未完成的任务
                for future in future_to_file:
                    future.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
                logger.info(f"✅ 已取消，成功上传 {success_count} 个文件")
                raise  # 重新抛出异常

        
        total_time = time.time() - start_time
        avg_speed = total_size / total_time if total_time > 0 else 0
        
        logger.info(
            f"上传完成: {success_count}/{total_files} 成功, "
            f"{total_size:.1f}MB, {total_time:.1f}s, {avg_speed:.1f}MB/s"
        )
        
        return results
    
    def batch_get_files(
        self, 
        file_list: List[Tuple[str, str, str]], 
        max_workers: int = 5
    ) -> Dict[str, Dict]:
        """
        并行批量下载文件
        
        Args:
            file_list: 文件列表，每个元素为 (file_id, minio_path, save_path) 元组
            max_workers: 最大并发数，默认 5
        
        Returns:
            下载结果字典，key 为 file_id，value 为下载结果
            
        Example:
            file_list = [
                ('file1', 'dxf/2026/01/xxx/file1.dxf', '/tmp/file1.dxf'),
                ('file2', 'dxf/2026/01/xxx/file2.dxf', '/tmp/file2.dxf'),
            ]
            results = minio_client.batch_get_files(file_list, max_workers=5)
        """
        if not self.client:
            logger.error("MinIO 客户端未初始化")
            return {}
        
        if not file_list:
            logger.warning("文件列表为空")
            return {}
        
        total_files = len(file_list)
        logger.info(f"🚀 开始并行下载 {total_files} 个文件，并发数: {max_workers}")
        
        start_time = time.time()
        results = {}
        success_count = 0
        failed_count = 0
        total_size = 0
        
        # 使用线程池并行下载
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有下载任务
            future_to_file = {
                executor.submit(self._download_single_file, file_info): file_info[0]
                for file_info in file_list
            }
            
            # 收集结果
            for future in as_completed(future_to_file):
                file_id = future_to_file[future]
                try:
                    result = future.result()
                    results[file_id] = result
                    
                    if result['success']:
                        success_count += 1
                        total_size += result.get('file_size', 0)
                        logger.info(
                            f"✅ [{success_count}/{total_files}] {file_id} "
                            f"({result['file_size']:.2f}MB, {result['download_time']:.2f}s)"
                        )
                    else:
                        failed_count += 1
                        logger.error(
                            f"❌ [{success_count + failed_count}/{total_files}] {file_id} "
                            f"失败: {result.get('error', '未知错误')}"
                        )
                        
                except Exception as e:
                    failed_count += 1
                    results[file_id] = {
                        'file_id': file_id,
                        'success': False,
                        'error': str(e)
                    }
                    logger.error(f"❌ {file_id} 下载异常: {e}")
        
        total_time = time.time() - start_time
        avg_speed = total_size / total_time if total_time > 0 else 0
        
        logger.info(
            f"📊 批量下载完成: 成功 {success_count}, 失败 {failed_count}, "
            f"总大小 {total_size:.2f}MB, 总耗时 {total_time:.2f}s, "
            f"平均速度 {avg_speed:.2f}MB/s"
        )
        
        return results


# 创建全局 MinIO 客户端实例
minio_client = MinIOClient()
