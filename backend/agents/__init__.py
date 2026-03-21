from .cad_agent import CADAgent
from .orchestrator_agent import OrchestratorAgent
from .pricing_agent import PricingAgent
from shared.config import settings
from shared.mcp_client import MCPClient


class _CadAgentAdapter:
    def __init__(self) -> None:
        self._agent = CADAgent(MCPClient(settings.CAD_PRICE_SEARCH_MCP_URL, timeout=settings.NC_AGENT_TIMEOUT))

    async def recognize_features_batch(self, payload: dict):
        return {
            "status": "accepted",
            "job_id": payload.get("job_id"),
            "total": len(payload.get("subgraph_ids", [])),
            "message": "已接收特征重识别请求，后续由内部服务处理。",
        }


class _PricingAgentAdapter:
    def __init__(self) -> None:
        self._agent = PricingAgent(MCPClient(settings.CAD_PRICE_SEARCH_MCP_URL, timeout=settings.NC_AGENT_TIMEOUT))

    async def calculate_batch(self, payload: dict):
        return {
            "status": "accepted",
            "job_id": payload.get("job_id"),
            "total_cost": None,
            "message": "已接收价格重算请求，后续由内部服务处理。",
        }


_cad_agent = None
_pricing_agent = None
_orchestrator_agent = None


def get_cad_agent():
    global _cad_agent
    if _cad_agent is None:
        _cad_agent = _CadAgentAdapter()
    return _cad_agent


def get_pricing_agent():
    global _pricing_agent
    if _pricing_agent is None:
        _pricing_agent = _PricingAgentAdapter()
    return _pricing_agent


def get_orchestrator_agent():
    global _orchestrator_agent
    if _orchestrator_agent is None:
        _orchestrator_agent = OrchestratorAgent()
    return _orchestrator_agent
