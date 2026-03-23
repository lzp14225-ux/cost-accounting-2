import asyncio
import json
import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class ProgressPublisher:
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
            from api_gateway.utils.redis_client import redis_client

            async def _publish() -> None:
                try:
                    if not redis_client.client:
                        await redis_client.connect()

                    await redis_client.publish(
                        f"job:{job_id}:progress",
                        json.dumps(payload, ensure_ascii=False),
                    )
                except Exception as exc:
                    logger.warning("Skip progress publish for job %s: %s", job_id, exc)

            asyncio.get_running_loop().create_task(_publish())
        except Exception:
            return

    def close(self) -> None:
        return
