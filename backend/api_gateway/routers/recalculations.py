"""
重算相关API路由
负责人：人员B2
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any

router = APIRouter(prefix="/api/v1", tags=["recalculations"])

class RecalculationRequest(BaseModel):
    subgraph_id: str
    reason: str
    modifications: Dict[str, Any]

class BatchRecalculationRequest(BaseModel):
    subgraph_ids: List[str]
    reason: str
    apply_new_version: bool = False

@router.post("/jobs/{job_id}/subgraphs/{subgraph_id}/recalculate")
async def recalculate_subgraph(
    job_id: str,
    subgraph_id: str,
    request: RecalculationRequest
):
    """单个子图重算"""
    return {"recalc_id": "uuid", "status": "pending"}

@router.post("/jobs/{job_id}/recalculate/batch")
async def batch_recalculate(
    job_id: str,
    request: BatchRecalculationRequest
):
    """批量子图重算"""
    return {"batch_recalc_id": "uuid", "status": "pending"}
