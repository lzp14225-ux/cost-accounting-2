"""
特征识别相关接口
负责人：后端同事
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/features", tags=["features"])


async def _execute_feature_recognition(
    cad_agent,
    job_id: str,
    subgraph_ids: List[str],
    force_reprocess: bool
):
    """
    后台执行特征识别任务
    
    Args:
        cad_agent: CADAgent 实例
        job_id: 任务ID
        subgraph_ids: 子图ID列表
        force_reprocess: 是否强制重新处理
    """
    try:
        logger.info(f"[后台任务] 开始执行特征识别: job_id={job_id}")
        
        # 调用批量特征识别方法（不发布进度）
        result = await cad_agent.recognize_features_batch({
            "job_id": job_id,
            "subgraph_ids": subgraph_ids,
            "force_reprocess": force_reprocess
        })
        
        logger.info(
            f"[后台任务] 特征识别完成: job_id={job_id}, "
            f"status={result.get('status')}, total={result.get('total')}"
        )
        
    except Exception as e:
        logger.error(f"[后台任务] 特征识别失败: job_id={job_id}, error={e}", exc_info=True)


class ReprocessRequest(BaseModel):
    """重新执行特征识别请求"""
    job_id: str
    subgraph_ids: List[str]
    force_reprocess: Optional[bool] = True
    
    class Config:
        schema_extra = {
            "example": {
                "job_id": "4fada577-6d86-4b8f-8c2e-0f991fd65a3c",
                "subgraph_ids": ["sub_001", "sub_002"],
                "force_reprocess": True
            }
        }


@router.post("/reprocess")
async def reprocess_features(request: ReprocessRequest):
    """
    重新执行特征识别（异步后台任务）
    
    用于用户修改参数后重新处理部分子图
    立即返回，处理在后台执行，通过 WebSocket 推送进度
    
    Args:
        request: 包含 job_id 和 subgraph_ids 的请求体
    
    Returns:
        {
            "status": "accepted",
            "message": "特征识别任务已提交，请通过 WebSocket 监听进度",
            "job_id": "xxx",
            "subgraph_count": 2
        }
    
    示例:
        ```bash
        curl -X POST ${FEATURE_REPROCESS_API_URL} \
          -H "Content-Type: application/json" \
          -d '{
            "job_id": "xxx",
            "subgraph_ids": ["sub_001", "sub_002"]
          }'
        ```
    """
    try:
        logger.info(
            f"收到特征识别请求: job_id={request.job_id}, "
            f"子图数量={len(request.subgraph_ids)}, "
            f"强制重新处理={request.force_reprocess}"
        )
        
        # 导入 Agent 工厂函数
        from agents import get_cad_agent
        
        # 获取 CADAgent 实例
        cad_agent = get_cad_agent()
        
        # 创建后台任务（不等待完成）
        asyncio.create_task(_execute_feature_recognition(
            cad_agent=cad_agent,
            job_id=request.job_id,
            subgraph_ids=request.subgraph_ids,
            force_reprocess=request.force_reprocess
        ))
        
        logger.info(f"特征识别任务已提交到后台: job_id={request.job_id}")
        
        # 立即返回
        return {
            "status": "accepted",
            "message": "特征识别任务已提交，请通过 WebSocket 监听进度",
            "job_id": request.job_id,
            "subgraph_count": len(request.subgraph_ids)
        }
        
    except Exception as e:
        logger.error(f"提交特征识别任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"提交任务失败: {str(e)}")


@router.get("/status/{job_id}")
async def get_features_status(job_id: str):
    """
    查询特征识别状态
    
    Args:
        job_id: 任务ID
    
    Returns:
        所有子图的特征识别状态
    """
    try:
        from shared.database import get_db
        from shared.models import Subgraph, Feature
        from sqlalchemy import select
        
        async for db in get_db():
            # 查询所有子图及其特征
            result = await db.execute(
                select(Subgraph, Feature)
                .outerjoin(Feature, Subgraph.subgraph_id == Feature.subgraph_id)
                .where(Subgraph.job_id == job_id)
            )
            
            rows = result.all()
            
            subgraphs_data = []
            for subgraph, feature in rows:
                subgraphs_data.append({
                    "subgraph_id": subgraph.subgraph_id,
                    "part_code": subgraph.part_code,
                    "has_features": feature is not None,
                    "features": {
                        "length_mm": feature.length_mm if feature else None,
                        "width_mm": feature.width_mm if feature else None,
                        "thickness_mm": feature.thickness_mm if feature else None,
                        "top_view_wire_length": feature.top_view_wire_length if feature else None,
                    } if feature else None
                })
            
            return {
                "status": "ok",
                "job_id": job_id,
                "total": len(subgraphs_data),
                "subgraphs": subgraphs_data
            }
            
    except Exception as e:
        logger.error(f"查询特征状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
