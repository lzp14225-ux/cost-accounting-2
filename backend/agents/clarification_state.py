"""
Clarification State Management - 澄清状态管理
负责人：人员B2

职责：
管理澄清状态的 Redis 存储和检索
"""
import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ClarificationStateManager:
    """澄清状态管理器"""
    
    # 默认 TTL：5分钟
    DEFAULT_TTL = 300
    
    def __init__(self):
        self._redis_client = None
        self._memory_cache = {}  # 内存缓存作为 fallback
    
    @property
    def redis_client(self):
        """懒加载 Redis 客户端"""
        if self._redis_client is None:
            from api_gateway.utils.redis_client import redis_client
            self._redis_client = redis_client
        return self._redis_client
    
    async def save_clarification_state(
        self,
        clarification_id: str,
        state: Dict[str, Any],
        ttl: int = DEFAULT_TTL
    ) -> bool:
        """
        保存澄清状态到 Redis
        
        Args:
            clarification_id: 澄清ID
            state: 状态数据
            ttl: 过期时间（秒）
        
        Returns:
            是否成功
        """
        logger.info(f"💾 保存澄清状态: clarification_id={clarification_id}")
        
        key = f"clarification:state:{clarification_id}"
        
        try:
            # 序列化状态
            state_json = json.dumps(state, ensure_ascii=False)
            
            # 保存到 Redis
            await self.redis_client.set(key, state_json, ex=ttl)
            
            logger.info(f"✅ 澄清状态已保存到 Redis")
            return True
        
        except Exception as e:
            logger.error(f"❌ 保存到 Redis 失败: {e}, 使用内存缓存")
            
            # Fallback: 使用内存缓存
            self._memory_cache[clarification_id] = state
            return True
    
    async def get_clarification_state(
        self,
        clarification_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取澄清状态
        
        Args:
            clarification_id: 澄清ID
        
        Returns:
            状态数据，如果不存在返回 None
        """
        logger.info(f"📖 获取澄清状态: clarification_id={clarification_id}")
        
        key = f"clarification:state:{clarification_id}"
        
        try:
            # 从 Redis 获取
            state_json = await self.redis_client.get(key)
            
            if state_json:
                state = json.loads(state_json)
                logger.info(f"✅ 从 Redis 获取澄清状态")
                return state
            else:
                logger.debug(f"Redis 中未找到状态")
                
                # Fallback: 检查内存缓存
                if clarification_id in self._memory_cache:
                    logger.info(f"✅ 从内存缓存获取澄清状态")
                    return self._memory_cache[clarification_id]
                
                return None
        
        except Exception as e:
            logger.error(f"❌ 从 Redis 获取失败: {e}")
            
            # Fallback: 检查内存缓存
            if clarification_id in self._memory_cache:
                logger.info(f"✅ 从内存缓存获取澄清状态")
                return self._memory_cache[clarification_id]
            
            return None
    
    async def delete_clarification_state(
        self,
        clarification_id: str
    ) -> bool:
        """
        删除澄清状态
        
        Args:
            clarification_id: 澄清ID
        
        Returns:
            是否成功
        """
        logger.info(f"🗑️  删除澄清状态: clarification_id={clarification_id}")
        
        key = f"clarification:state:{clarification_id}"
        
        try:
            # 从 Redis 删除
            await self.redis_client.delete(key)
            
            # 从内存缓存删除
            if clarification_id in self._memory_cache:
                del self._memory_cache[clarification_id]
            
            logger.info(f"✅ 澄清状态已删除")
            return True
        
        except Exception as e:
            logger.error(f"❌ 删除失败: {e}")
            return False


# 全局实例
_state_manager = None


def get_state_manager() -> ClarificationStateManager:
    """获取全局状态管理器实例"""
    global _state_manager
    if _state_manager is None:
        _state_manager = ClarificationStateManager()
    return _state_manager
