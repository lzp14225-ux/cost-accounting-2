"""
Agent 模块
提供统一的 Agent 实例获取接口
"""
from typing import Optional
from shared.mcp_client import MCPClient
from shared.progress_publisher import ProgressPublisher

# 全局单例
_cad_mcp_client: Optional[MCPClient] = None
_price_search_mcp_client: Optional[MCPClient] = None
_progress_publisher: Optional[ProgressPublisher] = None
_cad_agent = None
_pricing_agent = None
_nc_time_agent = None
_orchestrator_agent = None


def get_mcp_client() -> MCPClient:
    """获取统一的 MCP 客户端单例（CAD + 价格搜索 + 计算）"""
    global _cad_mcp_client
    if _cad_mcp_client is None:
        import os
        mcp_url = os.getenv("CAD_PRICE_SEARCH_MCP_URL", "http://localhost:8200")
        _cad_mcp_client = MCPClient(base_url=mcp_url, timeout=7200)  # 2小时超时
    return _cad_mcp_client


def get_cad_mcp_client() -> MCPClient:
    """获取 CAD MCP 客户端（使用统一的 MCP 服务）"""
    return get_mcp_client()


def get_price_search_mcp_client() -> MCPClient:
    """获取 Price Search MCP 客户端（使用统一的 MCP 服务）"""
    return get_mcp_client()


def get_progress_publisher() -> ProgressPublisher:
    """获取进度发布器单例"""
    global _progress_publisher
    if _progress_publisher is None:
        _progress_publisher = ProgressPublisher()
    return _progress_publisher


def get_cad_agent():
    """获取 CAD Agent 单例（MCP 模式）"""
    global _cad_agent
    
    if _cad_agent is None:
        from .cad_agent import CADAgent
        
        mcp_client = get_mcp_client()  # 使用统一的 MCP 客户端
        progress_publisher = get_progress_publisher()
        
        _cad_agent = CADAgent(
            mcp_client=mcp_client,
            progress_publisher=progress_publisher
        )
    
    return _cad_agent


def get_pricing_agent():
    """获取 Pricing Agent 单例"""
    global _pricing_agent
    
    if _pricing_agent is None:
        from .pricing_agent import PricingAgent
        
        mcp_client = get_mcp_client()  # 使用统一的 MCP 客户端
        progress_publisher = get_progress_publisher()
        
        _pricing_agent = PricingAgent(
            price_search_mcp_client=mcp_client,
            progress_publisher=progress_publisher
        )
    
    return _pricing_agent


def get_nc_time_agent():
    """获取 NCTimeAgent 单例"""
    global _nc_time_agent
    
    if _nc_time_agent is None:
        from .nc_time_agent import NCTimeAgent
        progress_publisher = get_progress_publisher()
        _nc_time_agent = NCTimeAgent(progress_publisher=progress_publisher)
    
    return _nc_time_agent


def get_orchestrator_agent():
    """
    获取 OrchestratorAgent 单例
    
    用于完整的自动化流程
    """
    global _orchestrator_agent
    
    if _orchestrator_agent is None:
        from .orchestrator_agent import OrchestratorAgent
        
        progress_publisher = get_progress_publisher()
        _orchestrator_agent = OrchestratorAgent(progress_publisher=progress_publisher)
        
        # 注册其他 Agent
        _orchestrator_agent.register_agents(
            cad_agent=get_cad_agent(),
            nc_time_agent=get_nc_time_agent(),
            pricing_agent=get_pricing_agent()
        )
    
    return _orchestrator_agent


# 导出常用的 Agent 类（供直接实例化使用）
from .base_agent import BaseAgent, OpResult
from .cad_agent import CADAgent
from .pricing_agent import PricingAgent
from .nc_time_agent import NCTimeAgent
from .orchestrator_agent import OrchestratorAgent

__all__ = [
    # 工厂函数
    "get_cad_agent",
    "get_pricing_agent",
    "get_nc_time_agent",
    "get_orchestrator_agent",
    "get_mcp_client",
    "get_progress_publisher",
    
    # Agent 类
    "BaseAgent",
    "OpResult",
    "CADAgent",
    "PricingAgent",
    "NCTimeAgent",
    "OrchestratorAgent",
]
