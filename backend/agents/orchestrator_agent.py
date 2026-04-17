"""
OrchestratorAgent - 编排Agent 
负责人：人员B1
版本：v2.0 - 简化流程，支持并行执行

职责：
1. 调度：按顺序/并行调用各 Agent
2. 状态管理：更新 jobs 表的状态和进度
3. 审计：写入 operation_logs 表
4. 汇总：更新 jobs 表的汇总数据
5. 进度发布：发布任务进度到Redis，供WebSocket实时推送

注意：
- 测试开发阶段使用 PricingAgentHTTP（直接调用 HTTP API）
- 生产环境使用 PricingAgent（MCP 模式）
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from .base_agent import BaseAgent
from shared.database import get_db
from shared.models import Job, OperationLog
from shared.progress_publisher import ProgressPublisher
from shared.progress_stages import ProgressStage, ProgressPercent

class OrchestratorAgent(BaseAgent):
    """
    编排Agent，负责整个工作流的编排和状态管理
    
    执行流程：
    1. CADAgent（串行）- 拆图 + 特征识别
    2. 暂停，等待用户确认特征识别结果
    3. 用户确认后继续：
       - DecisionAgent - 工艺决策（如果需要）
       - PricingAgent - 价格计算
    """
    
    def __init__(self, progress_publisher: Optional[ProgressPublisher] = None):
        super().__init__("OrchestratorAgent")
        self.version = "2.1.0"
        
        # 注册 Agent（由各负责人实现）
        self.cad_agent = None  # CADAgent 实例
        self.nc_time_agent = None  # NCTimeAgent 实例
        self.decision_agent = None  # DecisionAgent 实例
        self.pricing_agent = None  # PricingAgent 实例
        
        # 进度发布器
        self.progress_publisher = progress_publisher or ProgressPublisher()
    
    def register_agents(
        self,
        cad_agent,
        nc_time_agent=None,
        decision_agent=None,
        pricing_agent=None
    ):
        """注册各个 Agent 实例"""
        self.cad_agent = cad_agent
        self.nc_time_agent = nc_time_agent
        self.decision_agent = decision_agent
        self.pricing_agent = pricing_agent
    
    async def process(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        编排器不使用 process 方法
        使用 start() 方法作为入口
        """
        return {"status": "error", "message": "请使用 start() 方法", "error_code": "INVALID_METHOD"}
    
    async def start(self, job_id: str) -> Dict[str, Any]:
        """
        编排器入口方法
        从 RabbitMQ 消息消费后调用
        
        执行流程：
        1. CADAgent.split() - 拆图（生成2D子图）
        2. CADAgent.recognize_features() - 特征识别
        3. 暂停，等待用户确认
        
        用户确认后需调用 continue_job() 方法继续执行
        
        Args:
            job_id: 任务 ID
        
        Returns:
            执行结果字典，包含 action_required: "user_confirmation"
        """
        self.logger.info(f"[编排器] 开始处理任务: job_id={job_id}")
        start_time = datetime.utcnow()
        
        try:
            # 1. 验证 Job 是否存在
            import uuid
            try:
                job_uuid = uuid.UUID(job_id)
            except (ValueError, AttributeError):
                self.logger.error(f"[编排器] job_id 格式错误: job_id={job_id}")
                return {"status": "error", "message": "job_id 格式错误", "error_code": "INVALID_JOB_ID"}
            
            async for db in get_db():
                result = await db.execute(
                    select(Job).where(Job.job_id == job_uuid)
                )
                job = result.scalar_one_or_none()
                
                if not job:
                    self.logger.error(f"[编排器] Job 不存在: job_id={job_id}")
                    return {"status": "error", "message": "Job 不存在", "error_code": "JOB_NOT_FOUND"}
                break  # 只需要第一次迭代
            
            # 2. 更新状态：开始处理
            await self._update_job_status(
                job_id,
                status="processing",
                current_stage="initializing",
                progress=0
            )
            
            # 发布进度：初始化
            self._publish_progress(
                job_id,
                ProgressStage.INITIALIZING,
                ProgressPercent.INITIALIZING,
                "任务初始化..."
            )
            
            # ========== 阶段1：CADAgent 拆图 ==========
            self.logger.info(f"[编排器] 阶段1: CADAgent 拆图")
            
            if not self.cad_agent:
                return {"status": "error", "message": "CADAgent 未注册", "error_code": "AGENT_NOT_REGISTERED"}
            
            # 调用 CADAgent 的 split() 方法（拆图）
            # 进度由 MCP 服务内部发布
            split_result = await self._execute_agent_method(
                job_id,
                self.cad_agent,
                "CADAgent",
                "cad_split",
                method_name="split"
            )
            
            if split_result["status"] == "error":
                # 发布进度：拆图失败（MCP 服务可能已发布，这里作为兜底）
                self._publish_progress(
                    job_id,
                    ProgressStage.CAD_SPLIT_FAILED,
                    ProgressPercent.CAD_SPLIT_STARTED,
                    f"拆图失败: {split_result.get('message', '未知错误')}",
                    details={"error": split_result.get("message"), "error_code": split_result.get("error_code")}
                )
                await self._handle_failure(job_id, "cad_split", split_result)
                return split_result
            
            # 注意：拆图完成的进度已由 MCP 服务发布，这里不再重复发布
            
            # 更新进度
            subgraph_count = split_result.get("summary", {}).get("subgraph_count", 0)
            await self._update_job_status(
                job_id,
                current_stage="cad_split_completed",
                progress=20,
                total_subgraphs=subgraph_count
            )
            
            # ========== 阶段2：串行执行特征识别 -> NC 时间计算 ==========
            self.logger.info(f"[编排器] 阶段2: 先执行特征识别，再执行 NC 时间计算")
            
            # 获取文件路径（用于 NC Agent）
            async for db in get_db():
                result = await db.execute(
                    select(Job).where(Job.job_id == job_uuid)
                )
                job = result.scalar_one_or_none()
                dwg_file_path = job.dwg_file_path if job else None
                prt_file_path = job.prt_file_path if job else None
                break
            
            # 任务1：特征识别（必须先完成，确保 features 记录已经落库）
            feature_result = await self._execute_agent_method(
                job_id,
                self.cad_agent,
                "CADAgent",
                "feature_recognition",
                method_name="recognize_features"
            )
            nc_result = None
            
            # 检查特征识别结果（必须成功）
            if feature_result and feature_result["status"] == "error":
                # 发布进度：特征识别失败
                self._publish_progress(
                    job_id,
                    ProgressStage.FEATURE_RECOGNITION_FAILED,
                    ProgressPercent.FEATURE_RECOGNITION_STARTED,
                    f"特征识别失败: {feature_result.get('message', '未知错误')}",
                    details={"error": feature_result.get("message"), "error_code": feature_result.get("error_code")}
                )
                await self._handle_failure(job_id, "feature_recognition", feature_result)
                return feature_result

            # 任务2：NC 时间计算（仅当特征识别成功且有 NC Agent 且 prt_file_path 不为空时执行）
            if self.nc_time_agent:
                if prt_file_path and prt_file_path.strip():
                    self.logger.info(f"[编排器] 特征识别完成，开始执行 NC 时间计算: {prt_file_path}")
                    nc_result = await self._execute_agent_with_context(
                        job_id,
                        self.nc_time_agent,
                        "NCTimeAgent",
                        "nc_time_calculation",
                        context={
                            "job_id": job_id,
                            "dwg_file_path": dwg_file_path,
                            "prt_file_path": prt_file_path
                        }
                    )
                else:
                    self.logger.info("[编排器] prt_file_path 为空，跳过 NC 时间计算")
                    self._publish_progress(
                        job_id,
                        "nc_calculation_skipped",
                        ProgressPercent.FEATURE_RECOGNITION_COMPLETED,
                        "未上传PRT文件，跳过NC时间计算",
                        details={"reason": "prt_file_path_empty", "skipped": True}
                    )
            else:
                self.logger.warning("[编排器] NCTimeAgent 未注册，跳过 NC 时间计算")
            
            # NC 时间计算结果（失败不阻断流程）
            if nc_result:
                if nc_result["status"] == "error":
                    self.logger.warning(
                        f"[编排器] NC 时间计算失败，但继续执行: {nc_result.get('message')}"
                    )
                    # 更新 current_stage 为 nc_calculation_failed
                    # 让前端能看到这个失败状态
                    await self._update_job_status(
                        job_id,
                        current_stage="nc_calculation_failed",
                        progress=55
                    )
                    # 等待一小段时间，让前端有机会看到失败状态
                    await asyncio.sleep(2.0)
                else:
                    summary = nc_result.get('summary', {})
                    success_count = summary.get('success_count', 0)
                    total_count = summary.get('total_subgraphs', 0)
                    self.logger.info(
                        f"[编排器] NC 时间计算完成: success={success_count}/{total_count}"
                    )
                    # 更新 current_stage 为 nc_calculation_completed
                    await self._update_job_status(
                        job_id,
                        current_stage="nc_calculation_completed",
                        progress=70
                    )
            
            # 注意：特征识别和 NC 时间计算完成的进度已由各自的 Agent 发布到 Redis
            
            # 等待一小段时间，确保进度消息先到达
            await asyncio.sleep(0.1)
            
            # ========== 暂停，等待用户确认 ==========
            self.logger.info(f"[编排器] 特征识别和 NC 时间计算完成，等待用户确认")
            
            # 从结果中提取统计信息
            success_count = feature_result.get("summary", {}).get("success_count", 0)
            failed_count = feature_result.get("summary", {}).get("failed_count", 0)
            
            # 更新状态为等待确认
            await self._update_job_status(
                job_id,
                status="awaiting_confirm",
                current_stage="awaiting_confirm",
                progress=50
            )
            
            # 发布进度：等待用户确认（统一消息，不区分 NC 状态）
            self._publish_progress(
                job_id,
                ProgressStage.WAITING_FOR_CONFIRMATION,
                ProgressPercent.FEATURE_RECOGNITION_COMPLETED,
                "请检查结果并确认",
                details={
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "action_required": "user_confirmation"
                }
            )
            
            # 返回，不继续执行
            self.logger.info(f"[编排器] 任务暂停，等待用户确认: job_id={job_id}")
            self.logger.info("=" * 80)
            self.logger.info("!!! 重要：任务已暂停，等待用户确认特征识别结果 !!!")
            self.logger.info("!!! 用户需要调用 POST /api/v1/jobs/{job_id}/continue 才能继续 !!!")
            self.logger.info("=" * 80)
            return {
                "status": "ok",
                "message": "请检查结果并确认",
                "action_required": "user_confirmation",
                "summary": {
                    "job_id": job_id,
                    "success_count": success_count,
                    "failed_count": failed_count
                }
            }
            
        except Exception as e:
            self.logger.error(f"[编排器] 任务执行失败: job_id={job_id}, error={e}", exc_info=True)
            
            # 发布进度：任务失败
            self._publish_progress(
                job_id,
                ProgressStage.FAILED,
                0,
                f"任务执行失败: {str(e)}",
                details={"error": str(e)}
            )
            
            await self._update_job_status(
                job_id,
                status="failed",
                error_message=str(e)
            )
            return {"status": "error", "message": f"任务执行失败: {str(e)}", "error_code": "ORCHESTRATOR_ERROR"}
    
    async def continue_job(self, job_id: str) -> Dict[str, Any]:
        """
        用户确认特征识别结果后，继续执行后续流程
        
        执行流程：
        1. 验证任务状态是否为 waiting_for_confirmation
        2. DecisionAgent.process() - 工艺决策（如果有）
        3. PricingAgent.process() - 价格计算
        4. 完成任务
        
        Args:
            job_id: 任务 ID
        
        Returns:
            执行结果字典
        """
        self.logger.info("=" * 80)
        self.logger.info(f"[编排器] 用户确认完成，继续执行任务: job_id={job_id}")
        self.logger.info("=" * 80)
        start_time = datetime.utcnow()
        
        try:
            # 1. 验证 Job 状态
            import uuid
            try:
                job_uuid = uuid.UUID(job_id)
            except (ValueError, AttributeError):
                self.logger.error(f"[编排器] job_id 格式错误: job_id={job_id}")
                return {"status": "error", "message": "job_id 格式错误", "error_code": "INVALID_JOB_ID"}
            
            async for db in get_db():
                result = await db.execute(
                    select(Job).where(Job.job_id == job_uuid)
                )
                job = result.scalar_one_or_none()
                
                if not job:
                    self.logger.error(f"[编排器] Job 不存在: job_id={job_id}")
                    return {"status": "error", "message": "Job 不存在", "error_code": "JOB_NOT_FOUND"}
                
                # 验证状态
                if job.status != "awaiting_confirm":
                    self.logger.error(
                        f"[编排器] Job 状态不正确: job_id={job_id}, "
                        f"expected=awaiting_confirm, actual={job.status}"
                    )
                    return {
                        "status": "error",
                        "message": f"任务状态不正确，当前状态: {job.status}",
                        "error_code": "INVALID_STATUS"
                    }
                break  # 只需要第一次迭代
                break  # 只需要第一次迭代
            
            # 2. 更新状态：继续处理
            await self._update_job_status(
                job_id,
                status="processing",
                current_stage="continuing",
                progress=55
            )
            
            # 发布进度：继续执行
            self._publish_progress(
                job_id,
                "continuing",
                55,
                "用户确认完成，继续执行..."
            )
            
            # ========== 阶段3：查询 subgraph_ids ==========
            # 查询该 job 下的所有 subgraph_ids
            from shared.models import Subgraph
            async for db in get_db():
                result = await db.execute(
                    select(Subgraph.subgraph_id).where(Subgraph.job_id == job_uuid)
                )
                subgraph_ids = [row[0] for row in result.fetchall()]
                self.logger.info(f"[编排器] 查询到 {len(subgraph_ids)} 个子图")
                break
            
            # ========== 阶段4：PricingAgent 价格计算 ==========
            if self.pricing_agent:
                self.logger.info(f"[编排器] 阶段4: PricingAgent 价格计算")
                
                # 注意：价格计算的进度由 PricingAgent 内部发布
                pricing_result = await self._execute_agent_with_context(
                    job_id,
                    self.pricing_agent,
                    "PricingAgent",
                    "pricing_calculation",
                    context={"job_id": job_id, "subgraph_ids": subgraph_ids}
                )
                
                if pricing_result["status"] == "error":
                    await self._handle_failure(job_id, "pricing_calculation", pricing_result)
                    return pricing_result
                
                # 注意：jobs.total_cost 已由 PricingAgent 更新，这里不再重复更新
                # 只更新进度和阶段
                await self._update_job_status(
                    job_id,
                    current_stage="pricing_completed",
                    progress=90
                )
            
            # ========== 完成 ==========
            await self._update_job_status(
                job_id,
                status="completed",
                current_stage="completed",
                progress=100,
                completed_at=datetime.utcnow()
            )
            
            # 发布进度：任务完成
            duration = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self._publish_progress(
                job_id,
                ProgressStage.COMPLETED,
                ProgressPercent.COMPLETED,
                "任务完成！",
                details={"duration_ms": duration}
            )
            
            self.logger.info(f"[编排器] 任务完成: job_id={job_id}, 耗时={duration}ms")
            
            return {"status": "ok", "message": "任务处理完成", "summary": {"job_id": job_id, "duration_ms": duration}}
            
        except Exception as e:
            self.logger.error(f"[编排器] 任务继续执行失败: job_id={job_id}, error={e}", exc_info=True)
            
            # 发布进度：任务失败
            self._publish_progress(
                job_id,
                ProgressStage.FAILED,
                0,
                f"任务执行失败: {str(e)}",
                details={"error": str(e)}
            )
            
            await self._update_job_status(
                job_id,
                status="failed",
                error_message=str(e)
            )
            return {"status": "error", "message": f"任务执行失败: {str(e)}", "error_code": "ORCHESTRATOR_ERROR"}
    
    async def _execute_agent_method(
        self,
        job_id: str,
        agent: BaseAgent,
        agent_name: str,
        action: str,
        method_name: str = "process"
    ) -> Dict[str, Any]:
        """
        执行 Agent 的指定方法
        
        Args:
            job_id: 任务ID
            agent: Agent 实例
            agent_name: Agent 名称
            action: 操作名称
            method_name: 要调用的方法名（默认 "process"）
        
        Returns:
            Agent 执行结果
        """
        if not agent:
            return {"status": "error", "message": f"{agent_name} 未注册", "error_code": "AGENT_NOT_REGISTERED"}
        
        start_time = datetime.utcnow()
        
        try:
            self.logger.info(f"[编排器] 调用 {agent_name}.{method_name}()")
            
            # 获取 Agent 的方法
            method = getattr(agent, method_name, None)
            if not method:
                return {"status": "error", "message": f"{agent_name} 没有 {method_name} 方法", "error_code": "METHOD_NOT_FOUND"}
            
            # 调用方法
            result = await method({"job_id": job_id})
            
            # 计算执行时长
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # 记录操作日志
            await self._log_operation(
                job_id=job_id,
                agent=agent_name,
                action=action,
                result=result,
                duration_ms=duration_ms
            )
            
            self.logger.info(
                f"[编排器] {agent_name}.{method_name}() 执行完成: "
                f"status={result['status']}, duration={duration_ms}ms"
            )
            
            return result
            
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            error_msg = f"{agent_name}.{method_name}() 执行异常: {str(e)}"
            
            self.logger.error(f"[编排器] {error_msg}", exc_info=True)
            
            error_result = {"status": "error", "message": error_msg, "error_code": "AGENT_EXECUTION_ERROR"}
            
            # 记录错误日志
            await self._log_operation(
                job_id=job_id,
                agent=agent_name,
                action=action,
                result=error_result,
                duration_ms=duration_ms
            )
            
            return error_result
    
    async def _execute_agent(
        self,
        job_id: str,
        agent: BaseAgent,
        agent_name: str,
        action: str
    ) -> Dict[str, Any]:
        """
        执行单个 Agent（调用 process 方法）
        
        Args:
            job_id: 任务ID
            agent: Agent 实例
            agent_name: Agent 名称
            action: 操作名称
        
        Returns:
            Agent 执行结果
        """
        return await self._execute_agent_method(
            job_id, agent, agent_name, action, method_name="process"
        )
    
    async def _execute_agent_with_context(
        self,
        job_id: str,
        agent: BaseAgent,
        agent_name: str,
        action: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        执行单个 Agent（调用 process 方法，支持自定义 context）
        
        Args:
            job_id: 任务ID
            agent: Agent 实例
            agent_name: Agent 名称
            action: 操作名称
            context: 传递给 Agent 的上下文（默认为 {"job_id": job_id}）
        
        Returns:
            Agent 执行结果
        """
        if not agent:
            return {"status": "error", "message": f"{agent_name} 未注册", "error_code": "AGENT_NOT_REGISTERED"}
        
        start_time = datetime.utcnow()
        
        try:
            self.logger.info(f"[编排器] 调用 {agent_name}.process()")
            
            # 使用自定义 context 或默认 context
            agent_context = context or {"job_id": job_id}
            
            # 调用 Agent 的 process 方法
            result = await agent.process(agent_context)
            
            # 计算执行时长
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # 记录操作日志
            await self._log_operation(
                job_id=job_id,
                agent=agent_name,
                action=action,
                result=result,
                duration_ms=duration_ms
            )
            
            self.logger.info(
                f"[编排器] {agent_name}.process() 执行完成: "
                f"status={result['status']}, duration={duration_ms}ms"
            )
            
            return result
            
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            error_msg = f"{agent_name}.process() 执行异常: {str(e)}"
            
            self.logger.error(f"[编排器] {error_msg}", exc_info=True)
            
            error_result = {"status": "error", "message": error_msg, "error_code": "AGENT_EXECUTION_ERROR"}
            
            # 记录错误日志
            await self._log_operation(
                job_id=job_id,
                agent=agent_name,
                action=action,
                result=error_result,
                duration_ms=duration_ms
            )
            
            return error_result
    
    async def _update_job_status(
        self,
        job_id: str,
        status: str = None,
        current_stage: str = None,
        progress: int = None,
        total_subgraphs: int = None,
        total_cost: float = None,
        currency: str = None,
        completed_at: datetime = None,
        error_message: str = None
    ):
        """
        更新 jobs 表状态
        
        编排器职责：只更新状态、进度、汇总数据
        """
        async for db in get_db():
            update_data = {"updated_at": datetime.utcnow()}
            
            if status:
                update_data["status"] = status
            if current_stage:
                update_data["current_stage"] = current_stage
            if progress is not None:
                update_data["progress"] = progress
            if total_subgraphs is not None:
                update_data["total_subgraphs"] = total_subgraphs
            if total_cost is not None:
                update_data["total_cost"] = total_cost
            if currency:
                update_data["currency"] = currency
            if completed_at:
                update_data["completed_at"] = completed_at
            if error_message:
                update_data["error_message"] = error_message
            
            await db.execute(
                update(Job)
                .where(Job.job_id == job_id)
                .values(**update_data)
            )
            await db.commit()
            
            self.logger.debug(f"[编排器] 更新 jobs 表: job_id={job_id}, {update_data}")
            break  # 只需要第一次迭代
    
    async def _log_operation(
        self,
        job_id: str,
        agent: str,
        action: str,
        result: Dict[str, Any],
        duration_ms: int
    ):
        """
        写入 operation_logs 表
        
        编排器职责：记录所有 Agent 的操作审计日志
        """
        async for db in get_db():
            await db.execute(
                insert(OperationLog).values(
                    job_id=job_id,
                    subgraph_id=None,  # Agent 级别操作
                    agent=agent,
                    action=action,
                    input_data={"job_id": job_id},
                    output_data=result,
                    status=result.get("status", "unknown"),
                    duration_ms=duration_ms,
                    error_message=result.get("message") if result.get("status") == "error" else None,
                    created_at=datetime.utcnow()
                )
            )
            await db.commit()
            
            self.logger.debug(
                f"[编排器] 记录操作日志: agent={agent}, action={action}, "
                f"status={result.get('status')}, duration={duration_ms}ms"
            )
            break  # 只需要第一次迭代
    
    async def _handle_failure(
        self,
        job_id: str,
        stage: str,
        result: Dict[str, Any]
    ):
        """处理失败情况"""
        await self._update_job_status(
            job_id,
            status="failed",
            current_stage=stage,
            error_message=result.get("message", "未知错误")
        )
        
        self.logger.error(
            f"[编排器] 任务失败: job_id={job_id}, stage={stage}, "
            f"error={result.get('message')}"
        )

    def _publish_progress(
        self,
        job_id: str,
        stage: str,
        progress: int,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        发布进度到Redis
        
        Args:
            job_id: 任务ID
            stage: 阶段名称（使用 ProgressStage 常量）
            progress: 进度百分比 0-100
            message: 进度消息
            details: 额外的详细信息（可选）
        """
        if self.progress_publisher:
            self.progress_publisher.publish_progress(
                job_id=job_id,
                stage=stage,
                progress=progress,
                message=message,
                details=details
            )
