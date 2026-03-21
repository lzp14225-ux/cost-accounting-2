import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging
from config.config import get_config

# 获取配置
config = get_config()

class DatabaseManager:
    def __init__(self):
        self.config = config.get_database_config()
        self.logger = logging.getLogger(__name__)
        self.connection_pool = None
        self._initialize_pool()
    
    def _initialize_pool(self):
        """初始化数据库连接池"""
        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,      # 最小连接数
                maxconn=10,     # 最大连接数
                **self.config
            )
            self.logger.info("数据库连接池初始化成功 (min=2, max=10)")
        except Exception as e:
            self.logger.error(f"连接池初始化失败: {e}")
            # 如果连接池初始化失败，回退到传统连接方式
            self.connection_pool = None
            self.logger.warning("将使用传统连接方式（无连接池）")
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = None
        use_pool = self.connection_pool is not None
        
        try:
            if use_pool:
                # 从连接池获取连接
                conn = self.connection_pool.getconn()
            else:
                # 回退到传统方式
                conn = psycopg2.connect(**self.config)
            
            yield conn
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"数据库操作错误: {e}")
            raise
        finally:
            if conn:
                if use_pool:
                    # 归还连接到池中
                    self.connection_pool.putconn(conn)
                else:
                    # 关闭连接
                    conn.close()
    
    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        """执行查询"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                
                if fetch_one:
                    result = cursor.fetchone()
                    conn.commit()  # 提交事务
                    return dict(result) if result else None
                elif fetch_all:
                    results = cursor.fetchall()
                    conn.commit()  # 提交事务
                    return [dict(row) for row in results]
                else:
                    conn.commit()
                    return cursor.rowcount
    
    def execute_batch(self, queries_with_params):
        """
        批量执行多个查询（在同一个连接和事务中）
        
        Args:
            queries_with_params: 列表，每个元素是 (query, params) 元组
        
        Returns:
            每个查询影响的行数列表
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                results = []
                try:
                    for query, params in queries_with_params:
                        cursor.execute(query, params)
                        results.append(cursor.rowcount)
                    conn.commit()
                    return results
                except Exception as e:
                    conn.rollback()
                    self.logger.error(f"批量执行失败: {e}")
                    raise
    
    def test_connection(self):
        """测试数据库连接"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    return result is not None
        except Exception as e:
            self.logger.error(f"数据库连接测试失败: {e}")
            return False
    
    def close_all_connections(self):
        """关闭所有连接池连接（应用关闭时调用）"""
        if self.connection_pool:
            try:
                self.connection_pool.closeall()
                self.logger.info("数据库连接池已关闭")
            except Exception as e:
                self.logger.error(f"关闭连接池失败: {e}")

# 全局数据库管理器实例
db_manager = DatabaseManager()