"""
价格重算Worker
负责消费 pricing_recalculate 队列的消息并执行价格计算

运行方式:
    python -m workers.pricing_recalculate_worker
"""
import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared.message_queue import MessageQueue, QUEUE_PRICING_RECALCULATE
from agents import get_pricing_agent

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PricingRecalculateWorker:
    """价格重算Worker"""
    
    def __init__(self):
        self.mq = MessageQueue()
        self.pricing_agent = None
        logger.info("PricingRecalculateWorker 初始化")
    
    async def start(self):
        """启动Worker"""
        try:
            logger.info("=" * 80)
            logger.info("价格重算Worker启动中...")
            logger.info("=" * 80)
            logger.info(f"监听队列: {QUEUE_PRICING_RECALCULATE}")
            
            # 初始化 PricingAgent
            self.pricing_agent = get_pricing_agent()
            logger.info("✅ PricingAgent 初始化成功")
            
            # 开始消费消息
            await self.mq.consume(
                queue_name=QUEUE_PRICING_RECALCULATE,
                callback=self.handle_message,
                early_ack=True  # 提前确认，避免阻塞队列
            )
            
        except Exception as e:
            logger.error(f"Worker 启动失败: {e}", exc_info=True)
            raise
    
    async def handle_message(self, message: dict):
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
            f"[收到消息] job_id={job_id}, "
            f"子图数量={len(subgraph_ids)}, "
            f"用户参数={user_params}"
        )
        
        try:
            # 调用 PricingAgent 执行计算
            result = await self.pricing_agent.calculate_batch({
                "job_id": job_id,
                "subgraph_ids": subgraph_ids,
                "user_params": user_params
            })
            
            if result.get("status") in ["ok", "partial"]:
                logger.info(
                    f"[计算完成] job_id={job_id}, "
                    f"总成本={result.get('total_cost', 0):.2f}"
                )
            else:
                logger.error(
                    f"[计算失败] job_id={job_id}, "
                    f"错误={result.get('message')}"
                )
        
        except Exception as e:
            logger.error(
                f"[处理失败] job_id={job_id}, 错误={e}",
                exc_info=True
            )


async def main():
    """主函数"""
    worker = PricingRecalculateWorker()
    
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    except Exception as e:
        logger.error(f"Worker 异常退出: {e}", exc_info=True)
    finally:
        logger.info("Worker 已停止")


if __name__ == "__main__":
    asyncio.run(main())
