#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库操作模块
"""

import os
import uuid
import psycopg2
from psycopg2 import pool
from typing import Optional
from loguru import logger


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.db_pool = None
        self.config = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password
        }
        self.init_pool()
    
    def init_pool(self) -> bool:
        """初始化数据库连接池"""
        try:
            self.db_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                **self.config
            )
            logger.info(f"✅ 数据库连接池初始化成功: {self.config['host']}:{self.config['port']}/{self.config['database']}")
            return True
        except Exception as e:
            logger.error(f"❌ 数据库连接池初始化失败: {e}")
            return False
    
    def get_dwg_file_path(self, job_id: str) -> Optional[str]:
        """从数据库中根据 job_id 查询 dwg_file_path"""
        if not self.db_pool:
            logger.warning("数据库连接池未初始化")
            return None
        
        conn = None
        cursor = None
        try:
            try:
                job_uuid = uuid.UUID(job_id)
            except (ValueError, AttributeError) as e:
                logger.error(f"❌ job_id 格式错误（不是有效的 UUID）: {job_id}")
                return None
            
            conn = self.db_pool.getconn()
            cursor = conn.cursor()
            
            cursor.execute("SELECT dwg_file_path FROM jobs WHERE job_id = %s", (str(job_uuid),))
            result = cursor.fetchone()
            
            if result and result[0]:
                dwg_file_path = result[0]
                logger.info(f"✅ 从数据库查询到 dwg_file_path: {dwg_file_path}")
                return dwg_file_path
            else:
                logger.warning(f"⚠️ 未找到 job_id={job_id} 对应的 dwg_file_path")
                return None
                
        except Exception as e:
            logger.error(f"❌ 从数据库查询 dwg_file_path 失败: {e}")
            return None
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            if conn:
                self.db_pool.putconn(conn)

    def get_prt_file_path(self, job_id: str) -> Optional[str]:
        """从数据库中根据 job_id 查询 prt_file_path"""
        if not self.db_pool:
            logger.warning("数据库连接池未初始化")
            return None

        conn = None
        cursor = None
        try:
            try:
                job_uuid = uuid.UUID(job_id)
            except (ValueError, AttributeError):
                logger.error(f"❌ job_id 格式错误: {job_id}")
                return None

            conn = self.db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute("SELECT prt_file_path FROM jobs WHERE job_id = %s", (str(job_uuid),))
            result = cursor.fetchone()

            if result and result[0]:
                logger.info(f"✅ 从数据库查询到 prt_file_path: {result[0]}")
                return result[0]
            else:
                logger.warning(f"⚠️ 未找到 job_id={job_id} 对应的 prt_file_path")
                return None

        except Exception as e:
            logger.error(f"❌ 从数据库查询 prt_file_path 失败: {e}")
            return None
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                self.db_pool.putconn(conn)
    
    def save_subgraph(self, sub_code: str, file_url: str, source_file: str, job_id: str, part_name: str = None, part_code: str = None, xt_file_url: str = None) -> bool:
        """
        保存子图信息到数据库
        
        Args:
            sub_code: 子图编号
            file_url: MinIO 文件路径
            source_file: 源文件名
            job_id: 任务ID
            part_name: 零件名称
            part_code: 零件编号
            xt_file_url: .x_t 文件路径（可选）
        
        Returns:
            bool: 保存成功返回 True，失败返回 False
        """
        if not self.db_pool:
            logger.warning("数据库连接池未初始化，跳过数据库保存")
            return False
        
        conn = None
        cursor = None
        try:
            try:
                job_uuid = uuid.UUID(job_id)
            except (ValueError, AttributeError) as e:
                logger.error(f"❌ job_id 格式错误（不是有效的 UUID）: {job_id}")
                return False
            
            conn = self.db_pool.getconn()
            cursor = conn.cursor()
            
            # 验证 job_id 是否存在
            cursor.execute("SELECT job_id FROM jobs WHERE job_id = %s", (str(job_uuid),))
            if not cursor.fetchone():
                logger.error(f"❌ job_id 在 jobs 表中不存在: {job_uuid}")
                return False
            
            subgraph_id = f"{source_file}_{sub_code}"
            
            # 检查 subgraph_id 长度，如果超过50字符则记录警告
            if len(subgraph_id) > 50:
                logger.warning(f"⚠️ subgraph_id 长度超过50字符: {len(subgraph_id)} - {subgraph_id}")
                # 截断 source_file 部分，保留 sub_code 完整
                max_source_len = 50 - len(sub_code) - 1  # -1 for underscore
                if max_source_len > 0:
                    truncated_source = source_file[:max_source_len]
                    subgraph_id = f"{truncated_source}_{sub_code}"
                    logger.info(f"   截断后: {subgraph_id}")
                else:
                    # 如果 sub_code 本身就太长，只能截断整个 ID
                    subgraph_id = subgraph_id[:50]
                    logger.warning(f"   强制截断为: {subgraph_id}")
            
            # 如果没有提供 part_name，使用默认值
            if not part_name:
                part_name = '未识别'
            
            # 如果没有提供 part_code，使用 sub_code 作为默认值
            if not part_code:
                part_code = sub_code
            
            insert_sql = """
                INSERT INTO subgraphs (
                    subgraph_id, 
                    job_id,
                    part_name,
                    part_code, 
                    subgraph_file_url,
                    xt_file_url,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (subgraph_id) 
                DO UPDATE SET 
                    part_name = EXCLUDED.part_name,
                    part_code = EXCLUDED.part_code,
                    subgraph_file_url = EXCLUDED.subgraph_file_url,
                    xt_file_url = EXCLUDED.xt_file_url,
                    updated_at = NOW()
            """
            
            cursor.execute(insert_sql, (subgraph_id, str(job_uuid), part_name, part_code, file_url, xt_file_url))
            conn.commit()
            
            logger.debug(f"✅ 子图已保存到数据库: sub_code={sub_code}, 品名={part_name}, 编号={part_code}, 文件={file_url}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存子图信息到数据库失败: sub_code={sub_code}, 错误: {e}")
            logger.error(f"错误详情: {type(e).__name__}: {str(e)}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            if conn:
                self.db_pool.putconn(conn)
