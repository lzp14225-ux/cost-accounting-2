"""
第二期功能API路由（预留接口）
负责人：待定
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/phase2", tags=["phase2"])

# ============ 线割改精铣场景 ============
class WireToMillingRequest(BaseModel):
    """线割改精铣请求"""
    subgraph_id: str
    extrusion_height: float  # 拉伸高度(mm)
    reason: str

@router.post("/jobs/{job_id}/wire-to-milling")
async def wire_to_milling(job_id: str, request: WireToMillingRequest):
    """
    线割改精铣（2D转3D）
    - 将2D线割轮廓拉伸为3D实体
    - 调用NC Agent计算精铣成本
    """
    return {"change_id": "uuid", "status": "pending"}

# ============ 单个子图3D传入NC场景 ============
@router.post("/jobs/{job_id}/subgraphs/{subgraph_id}/nc-single")
async def calculate_single_nc(job_id: str, subgraph_id: str):
    """
    单个子图3D传入NC
    - 从完整3D PRT拆分出单个子图
    - 单独计算NC成本
    """
    return {"calc_id": "uuid", "status": "pending"}

# ============ 板料线生成场景 ============
@router.post("/jobs/{job_id}/generate-sheet-lines")
async def generate_sheet_lines(job_id: str):
    """
    生成板料线
    - 为每个2D子图生成外框线
    - 生成带板料线的DWG文件
    """
    return {"dwg_with_sheet_lines": "path/to/file.dwg"}

# ============ 多工艺并行处理场景 ============
class MultiProcessRequest(BaseModel):
    """多工艺处理请求"""
    enabled_processes: list[str]  # ["WIRE", "NC", "GRINDING", "EDM"]

@router.post("/jobs/{job_id}/multi-process")
async def multi_process_calculation(job_id: str, request: MultiProcessRequest):
    """
    多工艺并行处理
    - 动态加载多个工艺Agent
    - 并行计算各工艺成本
    """
    return {"job_id": job_id, "processes": request.enabled_processes}
