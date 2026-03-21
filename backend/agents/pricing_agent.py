"""
Pricing agent compatibility wrapper.
Routes legacy pricing requests to the consolidated cad-price-search MCP service.
"""

from typing import Any, Dict

from .base_agent import BaseAgent, OpResult


class PricingAgent(BaseAgent):
    def __init__(self, mcp_client):
        super().__init__("PricingAgent")
        self.mcp_client = mcp_client

    async def process(self, context: Dict[str, Any]) -> OpResult:
        try:
            subgraph_ids = context.get("subgraph_ids")
            if not subgraph_ids and context.get("subgraphs"):
                subgraph_ids = [
                    item.get("subgraph_id") or item.get("id")
                    for item in context.get("subgraphs", [])
                    if isinstance(item, dict) and (item.get("subgraph_id") or item.get("id"))
                ]

            result = await self.mcp_client.call_tool(
                "cad-price-search-mcp",
                "calculate_final_total_cost",
                {
                    "job_id": context.get("job_id"),
                    "subgraph_ids": subgraph_ids,
                },
            )

            return OpResult(
                status="ok",
                data=result,
                message="Pricing calculation submitted to consolidated MCP service",
            )
        except Exception as e:
            self.logger.error(f"Pricing calculation failed: {e}")
            return OpResult(status="error", message=str(e))
