import asyncio
import json
import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class ProgressPublisher:
    def __init__(self) -> None:
        self._publish_queues: dict[str, asyncio.Queue[Dict[str, Any]]] = {}
        self._publish_tasks: dict[str, asyncio.Task[None]] = {}

    async def _drain_queue(self, job_id: str) -> None:
        try:
            from api_gateway.utils.redis_client import redis_client

            if not redis_client.client:
                await redis_client.connect()

            queue = self._publish_queues[job_id]
            while True:
                payload = await queue.get()
                try:
                    await redis_client.publish(
                        f"job:{job_id}:progress",
                        json.dumps(payload, ensure_ascii=False),
                    )
                except Exception as exc:
                    logger.warning("Skip progress publish for job %s: %s", job_id, exc)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Progress worker stopped for job %s: %s", job_id, exc)
        finally:
            self._publish_tasks.pop(job_id, None)
            self._publish_queues.pop(job_id, None)

    def publish_progress(
        self,
        job_id: str,
        stage: str,
        progress: int,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "job_id": job_id,
            "stage": stage,
            "progress": progress,
            "message": message,
            "details": details or {},
        }
        logger.info("Progress update: %s", json.dumps(payload, ensure_ascii=False))
        try:
            loop = asyncio.get_running_loop()
            queue = self._publish_queues.get(job_id)
            if queue is None:
                queue = asyncio.Queue()
                self._publish_queues[job_id] = queue

            queue.put_nowait(payload)

            worker = self._publish_tasks.get(job_id)
            if worker is None or worker.done():
                self._publish_tasks[job_id] = loop.create_task(self._drain_queue(job_id))
        except Exception:
            return

    def close(self) -> None:
        for task in list(self._publish_tasks.values()):
            task.cancel()
