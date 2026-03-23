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
        logger.info("已关闭内嵌 worker 启动，当前仅启动 API 服务")
        return None

    worker_entry = settings.EMBEDDED_WORKER_ENTRY.strip()
    worker_path = PROJECT_ROOT / worker_entry

    if not worker_entry:
        logger.warning("未配置 EMBEDDED_WORKER_ENTRY，跳过 worker 启动")
        return None

    if not worker_path.exists():
        logger.error("worker 启动文件不存在: %s", worker_path)
        return None

    logger.info("启动内嵌 worker: %s", worker_path)
    return subprocess.Popen(
        [sys.executable, str(worker_path)],
        cwd=str(PROJECT_ROOT),
    )


def stop_worker_process(worker_process: Optional[subprocess.Popen]) -> None:
    if worker_process is None:
        return

    if worker_process.poll() is not None:
        return

    logger.info("正在停止内嵌 worker，pid=%s", worker_process.pid)
    worker_process.terminate()

    try:
        worker_process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("worker 超时未退出，强制结束，pid=%s", worker_process.pid)
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
        logger.warning("检测到启用内嵌 worker，main.py 已自动关闭 uvicorn reload 以避免重复启动 worker")
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
