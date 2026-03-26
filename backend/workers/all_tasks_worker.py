"""
全任务Worker - 处理所有后台任务
负责消费多个队列的消息并执行相应任务

包含：
1. orchestrator 队列 - 处理新任务的编排（拆图、特征识别、价格计算）
2. pricing_recalculate 队列 - 处理价格重算（用户修改参数后重新计算）

运行方式:
    python -m workers.all_tasks_worker
    
或者:
    python workers/all_tasks_worker.py
"""
import asyncio
import logging
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared.message_queue import MessageQueue, QUEUE_JOB_PROCESSING, QUEUE_PRICING_RECALCULATE
from agents import get_orchestrator_agent, get_pricing_agent
from shared.logging_config import (
    build_standard_file_formatter,
    create_daily_rotating_file_handler,
    get_log_rotation_settings,
)

# 配置日志：同时输出到控制台和文件
# 创建 logs 目录（如果不存在）
log_dir = project_root / "logs"
log_dir.mkdir(exist_ok=True)

# 日志文件路径
log_file = log_dir / "all_tasks_worker.log"

# 尝试使用 loguru（如果可用）
try:
    from loguru import logger
    log_settings = get_log_rotation_settings(default_level="INFO", default_retention_days=30)
    
    # 移除默认的 handler
    logger.remove()
    
    # 添加控制台输出
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG"  # 显示所有级别的日志
    )
    
    # 添加文件输出（带轮转、保留和压缩）
    logger.add(
        log_file,
        rotation=log_settings["rotation_label"],
        retention=f"{log_settings['retention_days']} days",
        compression=log_settings["compression"],
        encoding="utf-8",
        level=log_settings["level_name"],
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )
    
    logger.info(f"日志文件保存位置: {log_file} (使用 loguru，支持轮转和压缩)")
    
except ImportError:
    # 如果没有 loguru，使用标准 logging
    import logging
    
    logging.basicConfig(
        level=get_log_rotation_settings(default_level="INFO")["level"],
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            create_daily_rotating_file_handler(
                filename=log_file,
                level=get_log_rotation_settings(default_level="INFO")["level"],
                formatter=build_standard_file_formatter(),
                encoding='utf-8',
                delay=True,
            ),
            logging.StreamHandler()  # 输出到控制台
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info(f"日志文件保存位置: {log_file} (使用标准 logging，无轮转功能)")

# 从环境变量读取并发配置
JOB_PROCESSING_CONCURRENCY = int(os.getenv("JOB_PROCESSING_CONCURRENCY", "1"))
PRICING_RECALCULATE_CONCURRENCY = int(os.getenv("PRICING_RECALCULATE_CONCURRENCY", "3"))


class AllTasksWorker:
    """全任务Worker - 处理所有后台任务"""
    
    def __init__(self):
        self.mq = MessageQueue()
        self.orchestrator_agent = None
        self.pricing_agent = None
        logger.info("AllTasksWorker 初始化")
    
    async def start(self):
        """启动Worker - 同时监听多个队列"""
        try:
            logger.info("=" * 80)
            logger.info("全任务Worker启动中...")
            logger.info("=" * 80)
            
            # 连接消息队列
            logger.info("连接 RabbitMQ...")
            await self.mq.connect()
            logger.info("✅ RabbitMQ 连接成功")
            
            # 初始化 Agents
            logger.info("初始化 OrchestratorAgent...")
            self.orchestrator_agent = get_orchestrator_agent()
            logger.info("✅ OrchestratorAgent 初始化成功")
            
            logger.info("初始化 PricingAgent...")
            self.pricing_agent = get_pricing_agent()
            logger.info("✅ PricingAgent 初始化成功")
            
            logger.info("=" * 80)
            logger.info("开始监听队列:")
            logger.info(f"  1. {QUEUE_JOB_PROCESSING} - 新任务编排 (并发数: {JOB_PROCESSING_CONCURRENCY})")
            logger.info(f"  2. {QUEUE_PRICING_RECALCULATE} - 价格重算 (并发数: {PRICING_RECALCULATE_CONCURRENCY})")
            logger.info("=" * 80)
            
            # 创建两个消费任务
            tasks = [
                asyncio.create_task(self._consume_job_processing_queue()),
                asyncio.create_task(self._consume_pricing_queue())
            ]
            
            # 等待所有任务（会一直运行）
            await asyncio.gather(*tasks)
            
        except Exception as e:
            logger.error(f"Worker 启动失败: {e}", exc_info=True)
            raise
    
    async def _consume_job_processing_queue(self):
        """消费任务处理队列（串行处理，因为任务之间可能有依赖）"""
        logger.info(f"[任务处理队列] 开始监听 {QUEUE_JOB_PROCESSING} (并发数: {JOB_PROCESSING_CONCURRENCY})")
        await self.mq.consume(
            queue_name=QUEUE_JOB_PROCESSING,
            callback=self.handle_job_processing_message,
            early_ack=True,
            max_concurrent=JOB_PROCESSING_CONCURRENCY
        )
    
    async def _consume_pricing_queue(self):
        """消费价格重算队列（并发处理，任务之间独立）"""
        logger.info(f"[价格重算队列] 开始监听 {QUEUE_PRICING_RECALCULATE} (并发数: {PRICING_RECALCULATE_CONCURRENCY})")
        await self.mq.consume(
            queue_name=QUEUE_PRICING_RECALCULATE,
            callback=self.handle_pricing_message,
            early_ack=True,
            max_concurrent=PRICING_RECALCULATE_CONCURRENCY
        )
    
    async def handle_job_processing_message(self, message: dict):
        """
        处理任务处理消息（新任务）
        
        Args:
            message: {
                "job_id": str,
                "action": str,  # "start" 或 "continue"
                "timestamp": str
            }
        """
        job_id = message.get("job_id")
        action = message.get("action", "start")
        
        logger.info(
            f"[任务处理] 收到消息: job_id={job_id}, action={action}"
        )
        
        try:
            if action == "start":
                # 开始新任务
                result = await self.orchestrator_agent.start(job_id)
            elif action == "continue":
                # 继续任务（用户确认后）
                result = await self.orchestrator_agent.continue_job(job_id)
            else:
                logger.error(f"[任务处理] 未知操作: {action}")
                return
            
            if result.get("status") == "ok":
                logger.info(f"[任务处理] 任务处理成功: job_id={job_id}")
            else:
                logger.error(
                    f"[任务处理] 任务处理失败: job_id={job_id}, "
                    f"message={result.get('message')}"
                )
        
        except Exception as e:
            logger.error(
                f"[任务处理] 处理消息失败: job_id={job_id}, error={e}",
                exc_info=True
            )
    
    async def handle_pricing_message(self, message: dict):
        """
        处理价格重算消息
        
        Args:
            message: {
                "job_id": str,
                "subgraph_ids": List[str],
                "user_params": Dict[str, Any],
                "timestamp": str
            }
        """
        job_id = message.get("job_id")
        subgraph_ids = message.get("subgraph_ids", [])
        user_params = message.get("user_params", {})
        
        logger.info(
            f"[价格重算] 收到消息: job_id={job_id}, "
            f"子图数量={len(subgraph_ids)}"
        )
        
        try:
            # 调用 PricingAgent 重新计算
            result = await self.pricing_agent.process({
                "job_id": job_id,
                "subgraph_ids": subgraph_ids,
                "user_params": user_params
            })
            
            if result.get("status") in ["ok", "partial"]:
                total_cost = result.get("total_cost", 0)
                logger.info(
                    f"[价格重算] 计算成功: job_id={job_id}, "
                    f"总成本={total_cost:.2f}"
                )
            else:
                logger.error(
                    f"[价格重算] 计算失败: job_id={job_id}, "
                    f"message={result.get('message')}"
                )
        
        except Exception as e:
            logger.error(
                f"[价格重算] 处理消息失败: job_id={job_id}, error={e}",
                exc_info=True
            )


async def main():
    """主函数"""
    worker = AllTasksWorker()
    await worker.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n收到中断信号，Worker 正在关闭...")
    except Exception as e:
        logger.error(f"Worker 异常退出: {e}", exc_info=True)
        sys.exit(1)
