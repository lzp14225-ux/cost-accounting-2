"""
Redis客户端工具
负责人：ZZH
"""
import redis.asyncio as redis
from ..config import settings
from shared.logging_config import get_logger
from shared.logging_middleware import log_redis_operation

logger = get_logger(__name__)

class RedisClient:
    """Redis客户端"""
    
    def __init__(self):
        self.client = None
        self.pubsub = None
    
    async def connect(self):
        """连接Redis"""
        try:
            self.client = await redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            
            # 测试连接
            await self.client.ping()
            
            logger.info(f"✅ Redis连接成功: {settings.REDIS_URL}")
            print(f"✅ Redis连接成功")
            
        except Exception as e:
            logger.error(f"❌ Redis连接失败: {e}")
            print(f"❌ Redis连接失败: {e}")
            raise
    
    async def close(self):
        """关闭连接"""
        if self.pubsub:
            await self.pubsub.close()
        
        if self.client:
            await self.client.close()
            logger.info("❌ Redis连接已关闭")
            print("❌ Redis连接已关闭")
    
    async def publish(self, channel: str, message: str):
        """
        发布消息
        
        Args:
            channel: 频道名称
            message: 消息内容（JSON字符串）
        """
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        try:
            await self.client.publish(channel, message)
            # 记录日志（不记录完整内容，只记录摘要）
            log_redis_operation("publish", channel, f"<message_len={len(message)}>", success=True)
            logger.debug(f"📤 Redis消息已发布: channel={channel}")
        except Exception as e:
            log_redis_operation("publish", channel, success=False)
            raise
    
    async def subscribe(self, *patterns: str):
        """
        订阅频道（支持模式匹配和多频道）
        
        Args:
            *patterns: 频道模式，如 "job:*:progress", "job:*:review"
        
        Returns:
            PubSub对象
        """
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        self.pubsub = self.client.pubsub()
        
        # 使用模式订阅（支持通配符）
        await self.pubsub.psubscribe(*patterns)
        
        logger.info(f"✅ Redis订阅成功: patterns={patterns}")
        print(f"✅ Redis订阅成功: {', '.join(patterns)}")
        
        return self.pubsub
    
    async def lpush(self, key: str, value: str):
        """列表左侧推入"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        await self.client.lpush(key, value)
    
    async def ltrim(self, key: str, start: int, end: int):
        """列表修剪"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        await self.client.ltrim(key, start, end)
    
    async def expire(self, key: str, seconds: int):
        """设置过期时间"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        await self.client.expire(key, seconds)
    
    async def lrange(self, key: str, start: int, end: int):
        """获取列表范围"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        return await self.client.lrange(key, start, end)
    
    # ========== 审核系统需要的方法 ==========
    
    async def set(self, key: str, value: str, ex: int = None, nx: bool = False):
        """
        设置键值
        
        Args:
            key: 键
            value: 值
            ex: 过期时间（秒）
            nx: 仅当键不存在时设置
        
        Returns:
            是否成功
        """
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        try:
            result = await self.client.set(key, value, ex=ex, nx=nx)
            # 记录日志
            log_redis_operation("set", key, f"<len={len(value)}, ex={ex}>", success=True)
            return result
        except Exception as e:
            log_redis_operation("set", key, success=False)
            raise
    
    async def get(self, key: str):
        """获取键值"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        try:
            result = await self.client.get(key)
            # 记录日志
            if result:
                log_redis_operation("get", key, f"<len={len(result)}>", success=True)
            else:
                log_redis_operation("get", key, "<not_found>", success=True)
            return result
        except Exception as e:
            log_redis_operation("get", key, success=False)
            raise
    
    async def delete(self, key: str):
        """删除键"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        try:
            result = await self.client.delete(key)
            log_redis_operation("delete", key, success=True)
            return result
        except Exception as e:
            log_redis_operation("delete", key, success=False)
            raise
    
    async def exists(self, key: str):
        """检查键是否存在"""
        if not self.client:
            raise RuntimeError("Redis未连接")
        
        return await self.client.exists(key)

# 全局Redis客户端实例
redis_client = RedisClient()
