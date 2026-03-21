"""
编排器 Worker
负责人：架构组
功能：消费 RabbitMQ job_processing 队列，调用编排器处理任务
"""
import asyncio
import logging
import sys
import os
from typing import Dict, Any
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.message_queue import MessageQueue, QUEUE_JOB_PROCESSING
from shared.progress_publisher import ProgressPublisher
from shared.config import settings
from agents.orchestrator_agent import OrchestratorAgent
from agents.cad_agent import CADAgent
from agents.pricing_agent import PricingAgent
from shared.mcp_client import MCPClient  # 使用真实的 MCP 客户端

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OrchestratorWorker:
    """编排器 Worker"""
    
    def __init__(self, enable_retry: bool = False):
        """
        初始化 Worker
        
        Args:
            enable_retry: 是否启用失败重试（默认 False）
                - True: 系统异常时重新入队重试
                - False: 所有失败都不重试，直接移到死信队列
        """
        self.mq = MessageQueue()
        self.progress_publisher = None
        self.orchestrator = None
        self.running = False
        self.enable_retry = enable_retry
    
    async def start(self): 
        """启动 Worker"""
        logger.info("启动编排器 Worker...")
        
        try:
            # 连接 RabbitMQ
            await self.mq.connect()
            logger.info("已连接到 RabbitMQ")
            
            # 初始化进度发布器
            logger.info("正在初始化进度发布器...")
            self.progress_publisher = ProgressPublisher()
            logger.info("✅ 进度发布器初始化成功")
            
            # 初始化编排器
            logger.info("正在初始化编排器...")
            self.orchestrator = OrchestratorAgent(progress_publisher=self.progress_publisher)
            logger.info("编排器对象创建完成")
            
            # 创建并注册各个 Agent
            try:
                # 从环境变量读取统一的 MCP 服务地址
                mcp_url = os.getenv("CAD_PRICE_SEARCH_MCP_URL") or settings.CAD_PRICE_SEARCH_MCP_URL
                
                logger.info(f"正在创建 MCP 客户端...")
                logger.info(f"  CAD & Price Search MCP: {mcp_url}")
                
                # 创建统一的 MCP 客户端（CAD + 价格搜索 + 计算）
                mcp_client = MCPClient(base_url=mcp_url, timeout=7200)  # 2小时超时
                logger.info("✅ MCP 客户端创建成功")
                
                logger.info("正在创建 CADAgent（MCP 模式）...")
                cad_agent = CADAgent(
                    mcp_client=mcp_client,
                    progress_publisher=self.progress_publisher
                )
                logger.info("✅ CADAgent 创建成功（MCP 模式）")
                
                logger.info("正在创建 NCTimeAgent...")
                from agents.nc_time_agent import NCTimeAgent
                nc_time_agent = NCTimeAgent(
                    progress_publisher=self.progress_publisher
                )
                logger.info("✅ NCTimeAgent 创建成功")
                
                logger.info("正在创建 PricingAgent（Agent 层并发模式）...")
                pricing_agent = PricingAgent(
                    price_search_mcp_client=mcp_client,  # 使用同一个 MCP 客户端
                    progress_publisher=self.progress_publisher
                )
                logger.info("✅ PricingAgent 创建成功（Agent 层并发模式）")
                
                logger.info("正在注册 Agent 到编排器...")
                self.orchestrator.register_agents(
                    cad_agent=cad_agent,
                    nc_time_agent=nc_time_agent,
                    pricing_agent=pricing_agent
                )
                logger.info("✅ 编排器已初始化，已注册 CADAgent、NCTimeAgent 和 PricingAgent")
            except Exception as e:
                logger.error(f"❌ Agent 注册失败: {e}", exc_info=True)
                raise
            
            # 开始消费消息
            self.running = True
            logger.info(f"开始监听队列: {QUEUE_JOB_PROCESSING}")
            logger.info("⚡ 使用尽早 ACK 模式，避免 Consumer Timeout")
            
            # 使用 early_ack=True，避免长时间处理导致超时
            await self.mq.consume(QUEUE_JOB_PROCESSING, self.handle_message, early_ack=True)
            
        except Exception as e:
            logger.error(f"Worker 启动失败: {e}", exc_info=True)
            raise
    
    async def handle_message(self, message: Dict[str, Any]):
        """
        处理单个消息
        
        注意：使用尽早 ACK 模式时，此方法不需要返回值
        消息已经在调用前被 ACK，即使处理失败也不会重新入队
        """
        job_id = message.get("job_id")
        
        if not job_id:
            logger.error(f"消息缺少 job_id: {message}")
            return
        
        logger.info(f"收到任务消息: job_id={job_id}")
        
        # ========== 幂等性检查：防止重复处理 ==========
        try:
            from shared.models import Job
            from shared.database import get_db
            from sqlalchemy import select
            import uuid
            
            try:
                job_uuid = uuid.UUID(job_id)
            except (ValueError, AttributeError):
                logger.error(f"job_id 格式错误: {job_id}")
                return
            
            # 检查任务状态和必需字段
            async for db in get_db():
                result = await db.execute(
                    select(Job.status, Job.current_stage, Job.dwg_file_path).where(Job.job_id == job_uuid)
                )
                row = result.first()
                
                if not row:
                    logger.error(f"❌ 任务不存在: job_id={job_id}")
                    return
                
                job_status, current_stage, dwg_file_path = row
                
                # 验证必需字段
                if not dwg_file_path:
                    logger.error(f"❌ 任务缺少 dwg_file_path: job_id={job_id}")
                    # 更新任务状态为失败
                    from sqlalchemy import update
                    from datetime import datetime
                    await db.execute(
                        update(Job)
                        .where(Job.job_id == job_uuid)
                        .values(
                            status="failed",
                            error_message="任务创建不完整：缺少 DWG 文件路径",
                            updated_at=datetime.utcnow()
                        )
                    )
                    await db.commit()
                    
                    # 发布失败进度
                    if self.progress_publisher:
                        from shared.progress_stages import ProgressStage
                        self.progress_publisher.publish_progress(
                            job_id=job_id,
                            stage=ProgressStage.FAILED,
                            progress=0,
                            message="任务创建不完整：缺少 DWG 文件路径",
                            details={"error": "missing_dwg_file_path"}
                        )
                    
                    return  # 不处理不完整的任务
                
                # 如果任务正在处理，跳过
                if job_status == "processing":
                    logger.warning(
                        f"⚠️ 任务正在处理中，跳过重复执行: job_id={job_id}, "
                        f"status={job_status}, stage={current_stage}"
                    )
                    return
                
                # 如果任务已完成，跳过
                if job_status in ["completed", "awaiting_confirm"]:
                    logger.warning(
                        f"⚠️ 任务已完成或等待确认，跳过: job_id={job_id}, status={job_status}"
                    )
                    return
                
                # 如果任务失败，可以重新处理
                if job_status == "failed":
                    logger.info(f"任务之前失败，现在重新处理: job_id={job_id}")
                
                logger.info(f"✅ 任务验证通过: job_id={job_id}, dwg_file_path={dwg_file_path}")
                break  # 只需要第一次迭代
                
        except Exception as e:
            logger.error(f"幂等性检查失败: {e}", exc_info=True)
            # 继续处理，不因为检查失败而中断
        
        # ========== 执行任务 ==========
        try:
            # 调用编排器处理任务
            result = await self.orchestrator.start(job_id)
            
            status = result.get("status")
            
            if status == "ok":
                logger.info(f"✅ 任务处理成功: job_id={job_id}")
            elif status == "error":
                error_msg = result.get("message", "未知错误")
                logger.error(f"❌ 任务失败: job_id={job_id}, error={error_msg}")
            else:
                logger.warning(f"⚠️ 任务状态未知: job_id={job_id}, status={status}")
            
        except Exception as e:
            logger.error(f"❌ 处理任务时发生异常: job_id={job_id}, error={e}", exc_info=True)
            
            # 尽早 ACK 模式下，异常不会导致消息重新入队
            # 需要在这里记录错误，便于后续排查
            try:
                from shared.models import Job
                from shared.database import get_db
                from sqlalchemy import update
                from datetime import datetime
                
                async for db in get_db():
                    await db.execute(
                        update(Job)
                        .where(Job.job_id == job_id)
                        .values(
                            status="failed",
                            error_message=f"Worker 异常: {str(e)}",
                            updated_at=datetime.utcnow()
                        )
                    )
                    await db.commit()
                    break
            except Exception as db_error:
                logger.error(f"更新任务失败状态时出错: {db_error}", exc_info=True)
    
    async def stop(self):
        """停止 Worker"""
        logger.info("停止编排器 Worker...")
        self.running = False
        
        # 关闭进度发布器
        if self.progress_publisher:
            self.progress_publisher.close()
        
        await self.mq.close()
        logger.info("Worker 已停止")


async def main():
    """主函数"""
    # 从环境变量读取是否启用重试（默认不启用）
    enable_retry = os.getenv("ENABLE_MESSAGE_RETRY", "false").lower() == "true"
    
    worker = OrchestratorWorker(enable_retry=enable_retry)
    
    if enable_retry:
        logger.info("⚠️  消息重试已启用：系统异常时消息会重新入队")
    else:
        logger.info("✅ 消息重试已禁用：所有失败任务都会移到死信队列")
    
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"Worker 异常退出: {e}", exc_info=True)
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
