"""
NCTimeAgent - NC时间计算Agent
负责人：人员B1
"""
from typing import Dict, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from .base_agent import BaseAgent, OpResult
from shared.config import settings

class NCTimeAgent(BaseAgent):
    """
    NC时间计算Agent
    调用外部统一NC Agent计算钻孔、开粗、精铣时间
    """
    
    def __init__(self, nc_agent_url: str | None = None):
        super().__init__("NCTimeAgent")
        self.nc_agent_url = nc_agent_url or settings.NC_AGENT_URL
        self.timeout = settings.NC_AGENT_TIMEOUT
    
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """处理NC时间计算"""
        try:
            # 调用外部NC Agent
            result = await self.call_nc_agent_complete(
                dwg_file=context.get("dwg_file_path"),
                prt_file=context.get("prt_file_path"),
                material=context.get("material", "45#")
            )
            
            return OpResult(
                status="ok",
                data=result,
                message="NC时间计算完成"
            )
        except Exception as e:
            self.logger.error(f"NC calculation failed: {e}")
            # 降级处理：使用默认值
            return self._fallback_calculation(context)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4)
    )
    async def call_nc_agent_complete(
        self,
        dwg_file: str,
        prt_file: str,
        material: str
    ) -> Dict[str, Any]:
        """
        调用外部NC Agent完整计算接口
        返回：钻孔、开粗、精铣三种时间
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.nc_agent_url}/api/nc/estimate_complete",
                json={
                    "dwg_file": dwg_file,
                    "prt_file": prt_file,
                    "material": material
                }
            )
            response.raise_for_status()
            return response.json()
    
    def _fallback_calculation(self, context: Dict[str, Any]) -> OpResult:
        """降级处理：使用默认值或历史平均值"""
        return OpResult(
            status="warning",
            data={
                "drilling_time": 0.5,  # 默认0.5小时
                "roughing_time": 2.0,  # 默认2小时
                "milling_time": 1.5    # 默认1.5小时
            },
            message="NC Agent调用失败，使用默认值"
        )
