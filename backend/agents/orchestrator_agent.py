"""
OrchestratorAgent - 编排Agent
负责人：人员B1
"""
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from .base_agent import BaseAgent, OpResult
from .interaction_agent import InteractionAgent
import logging

logger = logging.getLogger(__name__)

class OrchestratorAgent(BaseAgent):
    """
    编排Agent，负责整个工作流的编排和状态管理
    使用LangGraph构建状态机
    """
    
    def __init__(self, use_llm_for_interaction: bool = False):
        """
        初始化 OrchestratorAgent
        
        Args:
            use_llm_for_interaction: 是否为 InteractionAgent 启用 LLM（默认 False）
        """
        super().__init__("OrchestratorAgent")
        
        # 初始化 InteractionAgent
        self.interaction_agent = InteractionAgent(use_llm=use_llm_for_interaction)
        logger.info(f"✅ OrchestratorAgent 初始化完成，InteractionAgent LLM={'启用' if use_llm_for_interaction else '禁用'}")
        
        self.workflow = self._build_workflow()
    
    def _build_workflow(self) -> StateGraph:
        """构建LangGraph工作流"""
        workflow = StateGraph(dict)
        
        # 定义节点
        workflow.add_node("initializing", self._stage_initializing)
        workflow.add_node("cad_parsing", self._stage_cad_parsing)
        workflow.add_node("feature_recognition", self._stage_feature_recognition)
        workflow.add_node("check_params", self._stage_check_params)
        workflow.add_node("waiting_input", self._stage_waiting_input)
        workflow.add_node("nc_calculation", self._stage_nc_calculation)
        workflow.add_node("decision", self._stage_decision)
        workflow.add_node("pricing", self._stage_pricing)
        workflow.add_node("report_generation", self._stage_report_generation)
        workflow.add_node("archiving", self._stage_archiving)
        
        # 定义边
        workflow.set_entry_point("initializing")
        workflow.add_edge("initializing", "cad_parsing")
        workflow.add_edge("cad_parsing", "feature_recognition")
        workflow.add_edge("feature_recognition", "check_params")
        
        # 条件分支：是否需要用户输入
        workflow.add_conditional_edges(
            "check_params",
            self._should_wait_for_input,
            {
                "wait": "waiting_input",
                "continue": "nc_calculation"
            }
        )
        
        workflow.add_edge("waiting_input", "nc_calculation")
        workflow.add_edge("nc_calculation", "decision")
        workflow.add_edge("decision", "pricing")
        workflow.add_edge("pricing", "report_generation")
        workflow.add_edge("report_generation", "archiving")
        workflow.add_edge("archiving", END)
        
        return workflow.compile()
    
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """执行工作流"""
        try:
            result = await self.workflow.ainvoke(context)
            return OpResult(status="ok", data=result)
        except Exception as e:
            self.logger.error(f"Workflow execution failed: {e}")
            return OpResult(status="error", message=str(e))
    
    # ========== 各阶段处理方法 ==========
    
    async def _stage_initializing(self, state: dict) -> dict:
        """阶段0：初始化"""
        state["stage"] = "initializing"
        state["progress"] = 0
        return state
    
    async def _stage_cad_parsing(self, state: dict) -> dict:
        """阶段1：CAD解析"""
        # 调用CADAgent
        state["stage"] = "cad_parsing"
        state["progress"] = 20
        return state
    
    async def _stage_feature_recognition(self, state: dict) -> dict:
        """阶段2：特征识别"""
        # 调用FeatureRecognitionAgent
        state["stage"] = "feature_recognition"
        state["progress"] = 40
        return state
    
    async def _stage_check_params(self, state: dict) -> dict:
        """
        阶段3：检查参数
        调用 InteractionAgent 检查参数完整性
        """
        logger.info(f"🔍 开始检查参数: job_id={state.get('job_id')}")
        
        state["stage"] = "check_params"
        
        # 调用 InteractionAgent
        try:
            result = await self.interaction_agent.process({
                "job_id": state.get("job_id"),
                "features": state.get("features", []),
                "user_input": state.get("user_input", {})  # 如果有用户输入
            })
            
            if result.status == "need_input":
                # 参数缺失，需要用户输入
                state["missing_params"] = result.data["missing_params"]
                state["interaction_prompt"] = result.data.get("prompt", "")
                logger.info(f"⚠️  参数缺失: {len(result.data['missing_params'])} 个")
            elif result.status == "ok":
                # 参数完整
                state["missing_params"] = []
                state["features"] = result.data.get("features", state.get("features", []))
                logger.info(f"✅ 参数完整，继续执行")
            else:
                # 错误
                logger.error(f"❌ InteractionAgent 返回错误: {result.message}")
                state["error"] = result.message
        
        except Exception as e:
            logger.error(f"❌ 参数检查失败: {e}", exc_info=True)
            state["error"] = str(e)
            state["missing_params"] = []
        
        return state
    
    async def _stage_waiting_input(self, state: dict) -> dict:
        """
        阶段4：等待用户输入
        
        此阶段会暂停工作流，等待用户通过 WebSocket 或 HTTP 提交输入
        用户输入后，会通过 RabbitMQ 消息恢复工作流
        """
        logger.info(f"⏸️  等待用户输入: job_id={state.get('job_id')}")
        
        state["stage"] = "waiting_input"
        
        # 这里需要推送交互卡片到前端
        # 通过 Redis Pub/Sub 或 WebSocket 推送
        interaction_data = {
            "type": "interaction_required",
            "job_id": state.get("job_id"),
            "missing_params": state.get("missing_params", []),
            "prompt": state.get("interaction_prompt", ""),
            "timestamp": self._get_timestamp()
        }
        
        # 推送到 Redis（由 WebSocket 管理器监听）
        try:
            await self._publish_interaction(state.get("job_id"), interaction_data)
            logger.info(f"📤 交互卡片已推送: job_id={state.get('job_id')}")
        except Exception as e:
            logger.error(f"❌ 推送交互卡片失败: {e}")
        
        # 注意：实际工作流会在这里暂停
        # 等待用户输入后，通过 RabbitMQ 消息恢复
        # 恢复时会重新进入 check_params 阶段
        
        return state
    
    async def _publish_interaction(self, job_id: str, data: dict):
        """
        推送交互需求到 Redis
        
        Args:
            job_id: 任务ID
            data: 交互数据
        """
        try:
            # 导入 Redis 客户端
            from api_gateway.utils.redis_client import redis_client
            import json
            
            channel = f"job:{job_id}:interaction"
            message = json.dumps(data)
            
            await redis_client.publish(channel, message)
            logger.info(f"✅ 交互消息已发布到 Redis: {channel}")
        
        except Exception as e:
            logger.error(f"❌ 发布交互消息失败: {e}")
            # 不抛出异常，避免中断工作流
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    async def _stage_nc_calculation(self, state: dict) -> dict:
        """阶段5：NC时间计算"""
        # 调用NCTimeAgent
        state["stage"] = "nc_calculation"
        state["progress"] = 60
        return state
    
    async def _stage_decision(self, state: dict) -> dict:
        """阶段6：工艺决策"""
        # 调用DecisionAgent
        state["stage"] = "decision"
        state["progress"] = 70
        return state
    
    async def _stage_pricing(self, state: dict) -> dict:
        """阶段7：价格计算"""
        # 调用PricingAgent
        state["stage"] = "pricing"
        state["progress"] = 85
        return state
    
    async def _stage_report_generation(self, state: dict) -> dict:
        """阶段8：报表生成"""
        # 调用ReportAgent
        state["stage"] = "report_generation"
        state["progress"] = 95
        return state
    
    async def _stage_archiving(self, state: dict) -> dict:
        """阶段9：审计归档"""
        state["stage"] = "archiving"
        state["progress"] = 100
        return state
    
    def _should_wait_for_input(self, state: dict) -> str:
        """判断是否需要等待用户输入"""
        if state.get("missing_params"):
            return "wait"
        return "continue"
