"""
消息队列模块
负责人：人员B1
"""
import aio_pika
import json
from typing import Dict, Any, Callable
from shared.config import settings

RABBITMQ_URL = settings.RABBITMQ_URL

class MessageQueue:
    """RabbitMQ消息队列封装"""
    
    def __init__(self):
        self.connection = None
        self.channel = None
    
    async def connect(self):
        """建立连接"""
        self.connection = await aio_pika.connect_robust(RABBITMQ_URL)
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=2)  # 每个Worker并发2个任务
    
    async def publish(self, queue_name: str, message: Dict[str, Any]):
        """发布消息"""
        queue = await self.channel.declare_queue(queue_name, durable=True)
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(message).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=queue_name
        )
    
    async def consume(
        self,
        queue_name: str,
        callback: Callable
    ):
        """消费消息"""
        queue = await self.channel.declare_queue(queue_name, durable=True)
        
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    data = json.loads(message.body.decode())
                    await callback(data)
    
    async def close(self):
        """关闭连接"""
        if self.connection:
            await self.connection.close()

# 队列名称常量
QUEUE_JOB_PROCESSING = "job_processing"
QUEUE_RECALCULATION = "recalculation_queue"
QUEUE_DEAD_LETTER = "dead_letter_queue"
