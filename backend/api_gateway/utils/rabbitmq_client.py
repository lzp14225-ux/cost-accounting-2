"""
RabbitMQ客户端工具类
处理消息发送、队列管理等操作
"""
import json
from typing import Dict, Any, Optional
import aio_pika
from aio_pika import Message, DeliveryMode, ExchangeType
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel

from ..config import settings
from shared.logging_config import get_logger
from shared.logging_middleware import log_rabbitmq_publish

logger = get_logger(__name__)


class RabbitMQClient:
    """RabbitMQ客户端封装"""
    
    def __init__(self):
        """初始化RabbitMQ客户端"""
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[AbstractRobustChannel] = None
        self.url = settings.RABBITMQ_URL
        self.queue_job_processing = settings.RABBITMQ_QUEUE_JOB_PROCESSING
        self.queue_dlx = settings.RABBITMQ_QUEUE_DLX
    
    async def connect(self):
        """连接到RabbitMQ"""
        if self.connection and not self.connection.is_closed:
            return
        
        try:
            # 创建连接（使用robust连接，自动重连）
            self.connection = await aio_pika.connect_robust(self.url)
            self.channel = await self.connection.channel()
            
            # 设置QoS（预取数量）
            await self.channel.set_qos(prefetch_count=10)
            
            # 声明死信交换机
            dlx_exchange = await self.channel.declare_exchange(
                name=f"{self.queue_dlx}_exchange",
                type=ExchangeType.DIRECT,
                durable=True
            )
            
            # 声明死信队列
            dlx_queue = await self.channel.declare_queue(
                name=self.queue_dlx,
                durable=True
            )
            
            # 绑定死信队列到死信交换机
            await dlx_queue.bind(dlx_exchange, routing_key=self.queue_dlx)
            
            # 声明主队列（配置死信交换机）
            await self.channel.declare_queue(
                name=self.queue_job_processing,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": f"{self.queue_dlx}_exchange",
                    "x-dead-letter-routing-key": self.queue_dlx,
                    "x-message-ttl": 86400000  # 消息TTL: 24小时
                }
            )
            
            logger.info(f"✅ RabbitMQ连接成功: {settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}")
            logger.info(f"✅ 队列已声明: {self.queue_job_processing}")
            logger.info(f"✅ 死信队列已声明: {self.queue_dlx}")
        
        except Exception as e:
            logger.error(f"❌ RabbitMQ连接失败: {e}")
            raise
    
    async def publish_message(
        self,
        queue: str,
        message: Dict[Any, Any],
        priority: int = 0
    ):
        """
        发布消息到队列
        
        Args:
            queue: 队列名称
            message: 消息内容（字典）
            priority: 消息优先级（0-9，数字越大优先级越高）
        """
        if not self.channel:
            await self.connect()
        
        try:
            # 将消息转为JSON
            message_body = json.dumps(message, ensure_ascii=False).encode("utf-8")
            
            # 创建消息对象
            aio_message = Message(
                body=message_body,
                delivery_mode=DeliveryMode.PERSISTENT,  # 持久化消息
                priority=priority,
                content_type="application/json",
                content_encoding="utf-8"
            )
            
            # 发布消息到默认交换机（直接路由到队列）
            await self.channel.default_exchange.publish(
                message=aio_message,
                routing_key=queue
            )
            
            # 记录日志
            log_rabbitmq_publish(queue, message, success=True)
            logger.info(f"✅ 消息已发送到队列 [{queue}]: {message.get('job_id', 'unknown')}")
        
        except Exception as e:
            # 记录失败日志
            log_rabbitmq_publish(queue, message, success=False)
            logger.error(f"❌ 消息发送失败: {e}")
            raise
    
    async def publish_job_message(self, job_id: str, user_id: str, **kwargs):
        """
        发布任务消息（便捷方法）
        
        Args:
            job_id: 任务ID
            user_id: 用户ID
            **kwargs: 其他参数
        """
        message = {
            "job_id": job_id,
            "user_id": user_id,
            **kwargs
        }
        await self.publish_message(self.queue_job_processing, message)
    
    async def close(self):
        """关闭连接"""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("✅ RabbitMQ连接已关闭")


# 全局RabbitMQ客户端实例
rabbitmq_client = RabbitMQClient()
