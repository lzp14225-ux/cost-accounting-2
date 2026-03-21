"""
WebSocket实时通信模块
负责人：ZZH
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List
from datetime import datetime
import json
import asyncio

from shared.logging_config import get_logger
from shared.logging_middleware import log_websocket_message

logger = get_logger(__name__)

class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # job_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.subscriber_task = None
        self.redis_client = None
    
    async def connect(self, websocket: WebSocket, job_id: str):
        """建立连接"""
        await websocket.accept()
        
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        
        self.active_connections[job_id].append(websocket)
        
        logger.info(f"✅ WebSocket连接建立: job_id={job_id}, 当前连接数={len(self.active_connections[job_id])}")
        print(f"✅ 连接建立: job_id={job_id}, 当前连接数={len(self.active_connections[job_id])}")
    
    def disconnect(self, websocket: WebSocket, job_id: str):
        """断开连接"""
        if job_id in self.active_connections:
            try:
                self.active_connections[job_id].remove(websocket)
                logger.info(f"❌ WebSocket连接断开: job_id={job_id}")
                print(f"❌ 连接断开: job_id={job_id}")
                
                # 如果该任务没有连接了，删除key
                if not self.active_connections[job_id]:
                    del self.active_connections[job_id]
                    logger.info(f"🗑️  任务连接池已清空: job_id={job_id}")
            except ValueError:
                logger.warning(f"⚠️  连接不在列表中: job_id={job_id}")
    
    async def broadcast(self, job_id: str, message: dict):
        """广播消息给指定任务的所有连接"""
        if job_id in self.active_connections:
            disconnected = []
            
            # 记录日志
            message_type = message.get("type", "unknown")
            log_websocket_message(job_id, message_type, message, direction="send")
            
            for connection in self.active_connections[job_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"❌ 发送消息失败: {e}")
                    disconnected.append(connection)
            
            # 清理断开的连接
            for conn in disconnected:
                self.disconnect(conn, job_id)
            
            logger.info(f"📤 消息已发送: job_id={job_id}, 接收者={len(self.active_connections[job_id])}")
            print(f"📤 消息已发送: job_id={job_id}, 接收者={len(self.active_connections[job_id])}")
        else:
            logger.warning(f"⚠️  没有活跃连接: job_id={job_id}")
    
    def get_connection_count(self, job_id: str = None) -> int:
        """获取连接数"""
        if job_id:
            return len(self.active_connections.get(job_id, []))
        return sum(len(conns) for conns in self.active_connections.values())
    
    def get_all_job_ids(self) -> List[str]:
        """获取所有有活跃连接的job_id"""
        return list(self.active_connections.keys())
    
    async def start_redis_subscriber(self):
        """
        启动Redis订阅器（后台任务）
        订阅多个频道：
        - job:*:progress (编排Agent进度消息)
        - job:*:review (交互Agent审核消息)
        """
        from .utils.redis_client import redis_client
        
        self.redis_client = redis_client
        
        logger.info("🚀 启动Redis订阅器...")
        print("🚀 启动Redis订阅器...")
        
        try:
            # 订阅多个频道模式
            pubsub = await redis_client.subscribe("job:*:progress", "job:*:review")
            
            logger.info("✅ Redis订阅器已启动")
            logger.info("   - job:*:progress (编排Agent进度)")
            logger.info("   - job:*:review (交互Agent审核)")
            print("✅ Redis订阅器已启动，监听 job:*:progress 和 job:*:review")
            
            # 持续监听消息
            async for message in pubsub.listen():
                # 模式订阅返回 'pmessage'，普通订阅返回 'message'
                if message['type'] == 'pmessage':
                    await self._handle_redis_message(message)
                elif message['type'] in ('subscribe', 'psubscribe'):
                    # 订阅确认消息，可以忽略
                    logger.debug(f"📝 订阅确认: {message}")
                    continue
        
        except asyncio.CancelledError:
            logger.info("🛑 Redis订阅器已取消")
            print("🛑 Redis订阅器已取消")
        except Exception as e:
            logger.error(f"❌ Redis订阅器错误: {e}", exc_info=True)
            print(f"❌ Redis订阅器错误: {e}")
    
    async def _handle_redis_message(self, message):
        """
        处理从Redis收到的消息
        
        Args:
            message: Redis消息
                {
                    'type': 'pmessage',
                    'pattern': b'job:*:progress',
                    'channel': b'job:uuid:progress',
                    'data': b'{"stage":"cad_parsing","progress":20,...}'
                }
        """
        try:
            # 解析频道名，提取job_id和频道类型
            channel = message['channel']
            if isinstance(channel, bytes):
                channel = channel.decode('utf-8')
            
            # 频道格式: job:{job_id}:{channel_type}
            parts = channel.split(':')
            if len(parts) >= 3:
                job_id = parts[1]
                channel_type = parts[2]  # 'progress' 或 'review'
            else:
                logger.warning(f"⚠️  无效的频道格式: {channel}")
                return
            
            # 解析消息内容
            data_str = message['data']
            if isinstance(data_str, bytes):
                data_str = data_str.decode('utf-8')
            
            data = json.loads(data_str)
            
            # 🆕 根据频道类型构造不同的 WebSocket 消息
            if channel_type == 'progress':
                # 进度消息：来自编排 Agent
                ws_message = {
                    "type": "progress",
                    "job_id": job_id,
                    "timestamp": datetime.now().isoformat(),
                    "data": data
                }
            elif channel_type == 'review':
                # 审核消息：来自交互 Agent，直接转发
                # 这些消息已经包含了正确的 type 字段
                ws_message = data
                if 'job_id' not in ws_message:
                    ws_message['job_id'] = job_id
                if 'timestamp' not in ws_message:
                    ws_message['timestamp'] = datetime.now().isoformat()
            else:
                logger.warning(f"⚠️  未知的频道类型: {channel_type}")
                return
            
            # 推送到WebSocket
            await self.broadcast(job_id, ws_message)
            
            # 保存到历史消息（Redis 短期缓存）
            await self._save_to_history(job_id, ws_message)
            
            # 🆕 只持久化 progress 消息到数据库
            # review 消息由 InteractionAgent 已经持久化过了
            if channel_type == 'progress':
                await self._persist_to_database(job_id, ws_message)
            
            logger.info(f"✅ Redis消息已处理: job_id={job_id}, channel={channel_type}, type={ws_message.get('type')}")
            print(f"✅ Redis消息已处理: job_id={job_id}, type={ws_message.get('type')}")
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON解析失败: {e}")
        except Exception as e:
            logger.error(f"❌ 处理Redis消息失败: {e}", exc_info=True)
    
    async def _save_to_history(self, job_id: str, message: dict):
        """
        保存消息到Redis历史（用于断线重连）
        
        Args:
            job_id: 任务ID
            message: 消息内容
        """
        try:
            if self.redis_client and self.redis_client.client:
                key = f"job:{job_id}:messages"
                
                # 保存消息
                await self.redis_client.lpush(key, json.dumps(message))
                
                # 只保留最近10条
                await self.redis_client.ltrim(key, 0, 9)
                
                # 设置1小时过期
                await self.redis_client.expire(key, 3600)
                
                logger.debug(f"💾 消息已保存到历史: job_id={job_id}")
        
        except Exception as e:
            logger.error(f"❌ 保存消息历史失败: {e}")
    
    async def _persist_to_database(self, job_id: str, ws_message: dict):
        """
        持久化消息到数据库
        
        Args:
            job_id: 任务ID
            ws_message: WebSocket 消息
        
        Note:
            只持久化来自 Redis 的 progress 消息
            其他消息（review_data, modification_confirmation 等）
            由 InteractionAgent 直接持久化，避免重复
        """
        try:
            # 🆕 只持久化 progress 消息
            # 其他消息由 InteractionAgent 在推送时已经持久化
            if ws_message.get('type') != 'progress':
                logger.debug(f"⏭️  跳过持久化（由 InteractionAgent 处理）: type={ws_message.get('type')}")
                return
            
            # 使用持久化管理器
            from agents.message_persistence_manager import get_persistence_manager
            from shared.database import get_db
            
            persistence_manager = get_persistence_manager()
            
            # 判断是否需要持久化
            if not persistence_manager.should_persist(ws_message):
                return
            
            # 获取数据库会话并持久化
            async for db_session in get_db():
                try:
                    await persistence_manager.persist_message(
                        job_id=job_id,
                        ws_message=ws_message,
                        db_session=db_session
                    )
                    await db_session.commit()
                    logger.debug(f"💾 消息已持久化到数据库: job_id={job_id}, type={ws_message.get('type')}")
                finally:
                    await db_session.close()
                break
        
        except Exception as e:
            # 持久化失败不应影响主流程
            logger.error(f"❌ 数据库持久化失败: {e}", exc_info=True)

manager = ConnectionManager()
