"""
CAD agent compatibility wrapper.
Routes legacy CAD requests to the consolidated cad-price-search MCP service.
"""

from typing import Any, Dict

from .base_agent import BaseAgent, OpResult


class CADAgent(BaseAgent):
    def __init__(self, mcp_client):
        super().__init__("CADAgent")
        self.mcp_client = mcp_client

    async def process(self, context: Dict[str, Any]) -> OpResult:
        try:
            result = await self.mcp_client.call_tool(
                "cad-price-search-mcp",
                "process_cad_and_features",
                {
                    "job_id": context.get("job_id"),
                    "dwg_url": context.get("dwg_url") or context.get("dwg_file_path"),
                },
            )

            return OpResult(
                status="ok",
                data=result,
                message="CAD processing submitted to consolidated MCP service",
            )
        except Exception as e:
            self.logger.error(f"CAD processing failed: {e}")
            return OpResult(status="error", message=str(e))
