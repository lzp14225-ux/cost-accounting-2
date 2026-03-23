"""
RabbitMQ message queue wrapper.
"""

import asyncio
import json
from typing import Any, Callable, Dict

import aio_pika

from shared.config import settings


QUEUE_JOB_PROCESSING = settings.RABBITMQ_QUEUE_JOB_PROCESSING or "job_processing"
QUEUE_PRICING_RECALCULATE = "pricing_recalculate"
QUEUE_RECALCULATION = "recalculation_queue"
QUEUE_DEAD_LETTER = settings.RABBITMQ_QUEUE_DLX or "job_processing_dlx"


class MessageQueue:
    """Minimal RabbitMQ wrapper used by workers."""

    def __init__(self):
        self.connection = None
        self.channel = None

    async def connect(self):
        """Create a robust RabbitMQ connection."""
        if self.connection and not self.connection.is_closed:
            return

        self.connection = await aio_pika.connect_robust(
            settings.RABBITMQ_URL,
            heartbeat=86400,
            client_properties={"connection_name": "mold_main_worker"},
        )
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=10)

    async def _declare_queue(self, queue_name: str):
        if self.channel is None:
            await self.connect()

        return await self.channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl": 86400000,
                "x-dead-letter-exchange": f"{QUEUE_DEAD_LETTER}_exchange",
                "x-dead-letter-routing-key": QUEUE_DEAD_LETTER,
            },
        )

    async def publish(self, queue_name: str, message: Dict[str, Any]):
        """Publish a message to a durable queue."""
        await self._declare_queue(queue_name)
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(message, ensure_ascii=False).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue_name,
        )

    async def consume(
        self,
        queue_name: str,
        callback: Callable,
        early_ack: bool = False,
        max_concurrent: int = 1,
    ):
        """
        Consume messages from a queue.

        `early_ack=True` acknowledges the message before callback execution.
        `max_concurrent` controls how many callbacks run at once.
        """
        queue = await self._declare_queue(queue_name)
        semaphore = asyncio.Semaphore(max(1, max_concurrent))
        tasks = set()

        async def process_message(message: aio_pika.abc.AbstractIncomingMessage):
            async with semaphore:
                if early_ack:
                    try:
                        data = json.loads(message.body.decode("utf-8"))
                        await message.ack()
                        await callback(data)
                    except json.JSONDecodeError:
                        try:
                            await message.ack()
                        except Exception:
                            pass
                    except Exception:
                        try:
                            if not message.processed:
                                await message.ack()
                        except Exception:
                            pass
                else:
                    try:
                        data = json.loads(message.body.decode("utf-8"))
                        result = await callback(data)
                        if result is False:
                            await message.reject(requeue=False)
                        else:
                            await message.ack()
                    except json.JSONDecodeError:
                        await message.reject(requeue=False)
                    except Exception:
                        await message.reject(requeue=True)

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                task = asyncio.create_task(process_message(message))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

                if len(tasks) >= max(1, max_concurrent):
                    done, pending = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    tasks = pending

    async def close(self):
        """Close the RabbitMQ connection."""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
