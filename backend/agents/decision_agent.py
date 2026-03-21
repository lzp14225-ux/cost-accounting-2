"""
DecisionAgent - 工艺决策Agent
负责人：人员E
"""
from typing import Dict, Any
from .base_agent import BaseAgent, OpResult

class DecisionAgent(BaseAgent):
    """
    工艺决策Agent
    根据特征参数决定工艺参数（线割模式、刀数等）
    """
    
    def __init__(self, db_client):
        super().__init__("DecisionAgent")
        self.db_client = db_client
    
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """处理工艺决策"""
        try:
            subgraph = context.get("subgraph")
            
            # 检查用户覆盖参数
            if context.get("user_overrides"):
                return OpResult(
                    status="ok",
                    data=context["user_overrides"],
                    message="使用用户覆盖参数"
                )
            
            # 查询工艺规则
            rules = await self._query_rules(
                thickness=subgraph.get("thickness_mm"),
                material=subgraph.get("material")
            )
            
            # 应用规则
            decision = self._apply_rules(rules, subgraph)
            
            return OpResult(
                status="ok",
                data=decision,
                message="工艺决策完成"
            )
        except Exception as e:
            self.logger.error(f"Decision failed: {e}")
            return OpResult(status="error", message=str(e))
    
    async def _query_rules(self, thickness: float, material: str):
        """查询工艺规则"""
        # 从PostgreSQL查询process_rules表
        query = """
        SELECT * FROM process_rules
        WHERE version_id = 'v1.0'
          AND feature_type = 'WIRE'
          AND is_deleted = false
        ORDER BY priority DESC
        """
        return await self.db_client.fetch(query)
    
    def _apply_rules(self, rules, subgraph):
        """应用规则"""
        # 默认规则
        decision = {
            "wire_mode": "mid",
            "wire_passes": "cut1"
        }
        
        # 根据厚度调整
        thickness = subgraph.get("thickness_mm", 0)
        if thickness > 50:
            decision["wire_mode"] = "slow"
            decision["wire_passes"] = "cut1_trim1"
        
        return decision
