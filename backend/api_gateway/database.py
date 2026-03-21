"""
数据库连接模块 - 兼容性包装
提供简单的数据库操作接口，使用 asyncpg
"""
import os
import asyncpg
from dotenv import load_dotenv
from typing import List, Dict, Any
from shared.config import settings

load_dotenv()

# 构建数据库连接参数
DB_CONFIG = {
    'host': settings.DB_HOST,
    'port': int(settings.DB_PORT),
    'user': settings.DB_USER,
    'password': settings.DB_PASSWORD,
    'database': settings.DB_NAME
}

print(f"[Database] 连接地址: postgresql://{DB_CONFIG['user']}:***@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")


class DatabaseWrapper:
    """数据库包装类，提供简单的异步数据库操作"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._pool = None
    
    async def _get_pool(self):
        """获取连接池（懒加载）"""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(**self.config, min_size=1, max_size=10)
        return self._pool
    
    async def fetch_all(self, query: str, *args) -> List[Dict]:
        """
        执行查询并返回所有结果
        
        Args:
            query: SQL 查询语句
            *args: 查询参数
        
        Returns:
            结果列表（每行转换为字典）
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def fetch_one(self, query: str, *args) -> Dict:
        """
        执行查询并返回单条结果
        
        Args:
            query: SQL 查询语句
            *args: 查询参数
        
        Returns:
            单条结果（转换为字典），如果没有结果则返回 None
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def execute(self, query: str, *args) -> str:
        """
        执行单条 SQL 语句（INSERT/UPDATE/DELETE）
        
        Args:
            query: SQL 语句
            *args: 参数
        
        Returns:
            执行结果状态
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def execute_many(self, query: str, args_list: List[tuple]) -> None:
        """
        批量执行 SQL 语句
        
        Args:
            query: SQL 语句
            args_list: 参数列表
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(query, args_list)
    
    async def close(self):
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None


# 创建全局数据库实例
db = DatabaseWrapper(DB_CONFIG)
