import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import uvicorn

from shared.config import settings


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


def start_worker_process() -> Optional[subprocess.Popen]:
    if not settings.START_EMBEDDED_WORKER:
        logger.info("Embedded worker disabled; starting API only")
        return None

    worker_entry = settings.EMBEDDED_WORKER_ENTRY.strip()
    if not worker_entry:
        logger.warning("EMBEDDED_WORKER_ENTRY is empty; skipping embedded worker startup")
        return None

    worker_path = PROJECT_ROOT / worker_entry
    if not worker_path.exists():
        logger.error("Embedded worker entry not found: %s", worker_path)
        return None

    logger.info("Starting embedded worker: %s", worker_path)
    return subprocess.Popen(
        [sys.executable, str(worker_path)],
        cwd=str(PROJECT_ROOT),
    )


def stop_worker_process(worker_process: Optional[subprocess.Popen]) -> None:
    if worker_process is None or worker_process.poll() is not None:
        return

    logger.info("Stopping embedded worker pid=%s", worker_process.pid)
    worker_process.terminate()

    try:
        worker_process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("Embedded worker did not exit in time; killing pid=%s", worker_process.pid)
        worker_process.kill()
        worker_process.wait(timeout=5)


if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    worker_process = None
    reload_enabled = settings.RELOAD

    if settings.START_EMBEDDED_WORKER and reload_enabled:
        logger.warning(
            "Embedded worker is enabled; uvicorn reload is disabled to avoid duplicate worker processes"
        )
        reload_enabled = False

    try:
        worker_process = start_worker_process()
        uvicorn.run(
            "api_gateway.main:app",
            host=settings.API_GATEWAY_HOST,
            port=settings.UNIFIED_PORT,
            reload=reload_enabled,
            log_level=settings.LOG_LEVEL.lower(),
        )
    finally:
        stop_worker_process(worker_process)
