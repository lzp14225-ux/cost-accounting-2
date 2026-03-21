"""
审核系统 RabbitMQ 消费者
负责人：人员B2

职责：
1. 监听 review_queue 队列
2. 解析消息并调用 InteractionAgent
3. 实现错误重试机制
4. 添加日志记录

阶段2.2实现
"""
import asyncio
import json
from typing import Optional
import aio_pika
from aio_pika import Message, DeliveryMode
from aio_pika.abc import AbstractIncomingMessage

from api_gateway.config import settings
from shared.database import get_db  # 修复：使用 shared.database
from agents.interaction_agent import InteractionAgent
from shared.logging_config import get_logger

logger = get_logger(__name__)


class ReviewConsumer:
    """
    审核系统消息消费者
    
    监听队列：review_queue
    消息格式：
    {
        "action": "start_review",
        "job_id": "xxx",
        "user_id": "xxx"
    }
    """
    
    def __init__(self):
        """初始化消费者"""
        self.connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self.channel: Optional[aio_pika.abc.AbstractRobustChannel] = None
        self.queue_name = "review_queue"
        self.rabbitmq_url = settings.RABBITMQ_URL
        self.max_retries = 3  # 最大重试次数
        self.retry_delay = 5  # 重试延迟（秒）
        
        # InteractionAgent 实例
        self.agent = InteractionAgent()
    
    async def connect(self):
        """连接到 RabbitMQ"""
        try:
            logger.info(f"🔌 连接到 RabbitMQ: {settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}")
            
            # 创建连接（使用 robust 连接，自动重连）
            self.connection = await aio_pika.connect_robust(self.rabbitmq_url)
            self.channel = await self.connection.channel()
            
            # 设置 QoS（预取数量）
            await self.channel.set_qos(prefetch_count=5)
            
            # 声明队列（如果不存在则创建）
            queue = await self.channel.declare_queue(
                name=self.queue_name,
                durable=True,  # 持久化队列
                arguments={
                    "x-message-ttl": 3600000,  # 消息TTL: 1小时
                }
            )
            
            logger.info(f"✅ RabbitMQ 连接成功")
            logger.info(f"✅ 队列已声明: {self.queue_name}")
            
            return queue
        
        except Exception as e:
            logger.error(f"❌ RabbitMQ 连接失败: {e}", exc_info=True)
            raise
    
    async def start_consuming(self):
        """
        开始消费消息
        
        这是一个长期运行的任务，会持续监听队列
        """
        try:
            # 连接并获取队列
            queue = await self.connect()
            
            logger.info(f"🚀 开始监听队列: {self.queue_name}")
            print(f"🚀 ReviewConsumer 已启动，监听队列: {self.queue_name}")
            
            # 开始消费消息
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    await self._process_message(message)
        
        except asyncio.CancelledError:
            logger.info("🛑 消费者已取消")
            print("🛑 ReviewConsumer 已停止")
        
        except Exception as e:
            logger.error(f"❌ 消费者异常: {e}", exc_info=True)
            print(f"❌ ReviewConsumer 异常: {e}")
    
    async def _process_message(self, message: AbstractIncomingMessage):
        """
        处理单条消息
        
        Args:
            message: RabbitMQ 消息
        """
        async with message.process():
            try:
                # 解析消息
                body = message.body.decode("utf-8")
                data = json.loads(body)
                
                logger.info(f"📨 收到消息: {data}")
                
                # 验证消息格式
                if not self._validate_message(data):
                    logger.error(f"❌ 消息格式无效: {data}")
                    # 无效消息直接 ACK（不重试）
                    return
                
                # 获取重试次数
                retry_count = data.get("_retry_count", 0)
                
                # 处理消息
                success = await self._handle_message(data)
                
                if success:
                    logger.info(f"✅ 消息处理成功: job_id={data.get('job_id')}")
                else:
                    # 处理失败，检查是否需要重试
                    if retry_count < self.max_retries:
                        logger.warning(f"⚠️ 消息处理失败，准备重试 ({retry_count + 1}/{self.max_retries})")
                        await self._retry_message(data, retry_count + 1)
                    else:
                        logger.error(f"❌ 消息处理失败，已达最大重试次数: {data}")
            
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON 解析失败: {e}")
                # JSON 解析失败，直接 ACK（不重试）
            
            except Exception as e:
                logger.error(f"❌ 处理消息异常: {e}", exc_info=True)
                # 其他异常，消息会被 NACK 并重新入队
                raise
    
    def _validate_message(self, data: dict) -> bool:
        """
        验证消息格式
        
        Args:
            data: 消息数据
        
        Returns:
            是否有效
        """
        # 必需字段
        required_fields = ["action", "job_id"]
        
        for field in required_fields:
            if field not in data:
                logger.error(f"❌ 缺少必需字段: {field}")
                return False
        
        # 验证 action
        valid_actions = ["start_review"]
        if data["action"] not in valid_actions:
            logger.error(f"❌ 无效的 action: {data['action']}")
            return False
        
        return True
    
    async def _handle_message(self, data: dict) -> bool:
        """
        处理消息（调用 InteractionAgent）
        
        Args:
            data: 消息数据
        
        Returns:
            是否成功
        """
        try:
            action = data["action"]
            job_id = data["job_id"]
            
            logger.info(f"🔧 处理动作: action={action}, job_id={job_id}")
            
            if action == "start_review":
                # 启动审核
                async for db in get_db():
                    result = await self.agent.start_review(
                        job_id=job_id,
                        db_session=db
                    )
                    
                    if result.status == "ok":
                        logger.info(f"✅ 审核启动成功: job_id={job_id}")
                        return True
                    else:
                        logger.error(f"❌ 审核启动失败: {result.message}")
                        return False
            
            else:
                logger.error(f"❌ 未知的 action: {action}")
                return False
        
        except Exception as e:
            logger.error(f"❌ 处理消息失败: {e}", exc_info=True)
            return False
    
    async def _retry_message(self, data: dict, retry_count: int):
        """
        重试消息
        
        Args:
            data: 消息数据
            retry_count: 当前重试次数
        """
        try:
            # 添加重试计数
            data["_retry_count"] = retry_count
            
            # 延迟后重新发送
            await asyncio.sleep(self.retry_delay)
            
            # 发送到队列
            message_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            message = Message(
                body=message_body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
                content_encoding="utf-8"
            )
            
            await self.channel.default_exchange.publish(
                message=message,
                routing_key=self.queue_name
            )
            
            logger.info(f"🔄 消息已重新入队: retry_count={retry_count}")
        
        except Exception as e:
            logger.error(f"❌ 重试消息失败: {e}", exc_info=True)
    
    async def close(self):
        """关闭连接"""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("✅ RabbitMQ 连接已关闭")


# 全局消费者实例
review_consumer = ReviewConsumer()


# ========== 独立运行支持 ==========

async def main():
    """
    独立运行消费者
    
    使用方法：
        python -m consumers.review_consumer
    """
    consumer = ReviewConsumer()
    
    try:
        await consumer.start_consuming()
    except KeyboardInterrupt:
        logger.info("🛑 收到停止信号")
        print("\n🛑 停止消费者...")
    finally:
        await consumer.close()


if __name__ == "__main__":
    # 配置日志（独立运行时）
    from shared.logging_config import setup_logging
    setup_logging(level="INFO")
    
    print("=" * 60)
    print("审核系统 RabbitMQ 消费者")
    print("=" * 60)
    print(f"队列: review_queue")
    print(f"RabbitMQ: {settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}")
    print("=" * 60)
    print("按 Ctrl+C 停止")
    print("=" * 60)
    
    # 运行消费者
    asyncio.run(main())
