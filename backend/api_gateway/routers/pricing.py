"""
价格计算相关接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


async def _execute_pricing_calculation(
    pricing_agent,
    job_id: str,
    subgraph_ids: List[str],
    user_params: Dict[str, Any]
):
    """
    后台执行价格计算任务
    
    Args:
        pricing_agent: PricingAgent 实例
        job_id: 任务ID
        subgraph_ids: 子图ID列表
        user_params: 用户参数
    """
    try:
        logger.info(f"[后台任务] 开始执行价格计算: job_id={job_id}")
        
        # 调用批量价格计算方法（不发布进度）
        result = await pricing_agent.calculate_batch({
            "job_id": job_id,
            "subgraph_ids": subgraph_ids,
            "user_params": user_params
        })
        
        logger.info(
            f"[后台任务] 价格计算完成: job_id={job_id}, "
            f"status={result.get('status')}, total_cost={result.get('total_cost')}"
        )
        
    except Exception as e:
        logger.error(f"[后台任务] 价格计算失败: job_id={job_id}, error={e}", exc_info=True)


class RecalculateRequest(BaseModel):
    """重新计算价格请求"""
    job_id: str
    subgraph_ids: List[str]
    user_params: Optional[Dict[str, Any]] = None
    
    class Config:
        schema_extra = {
            "example": {
                "job_id": "4fada577-6d86-4b8f-8c2e-0f991fd65a3c",
                "subgraph_ids": ["sub_001"],
                "user_params": {
                    "material": "SKD11",
                    "material_price_override": 50.0
                }
            }
        }


@router.post("/recalculate")
async def recalculate_pricing(request: RecalculateRequest):
    """
    重新计算价格（通过消息队列异步处理）
    
    用于用户修改参数后重新计算部分子图的价格
    立即返回，计算通过消息队列在后台执行，通过 WebSocket 推送进度
    
    Args:
        request: 包含 job_id, subgraph_ids 和可选的 user_params
    
    Returns:
        {
            "status": "accepted",
            "message": "价格计算任务已提交到队列",
            "job_id": "xxx",
            "subgraph_count": 2
        }
    
    示例:
        ```bash
        curl -X POST ${PRICING_RECALCULATE_API_URL} \
          -H "Content-Type: application/json" \
          -d '{
            "job_id": "xxx",
            "subgraph_ids": ["sub_001"],
            "user_params": {"material": "SKD11"}
          }'
        ```
    """
    try:
        logger.info(
            f"收到价格计算请求: job_id={request.job_id}, "
            f"子图数量={len(request.subgraph_ids)}, "
            f"用户参数={request.user_params}"
        )
        
        # 导入消息队列
        from shared.message_queue import MessageQueue, QUEUE_PRICING_RECALCULATE
        
        # 创建消息队列实例（会自动连接）
        mq = MessageQueue()
        
        # 发布消息到队列（不等待处理）
        await mq.publish(
            queue_name=QUEUE_PRICING_RECALCULATE,
            message={
                "job_id": request.job_id,
                "subgraph_ids": request.subgraph_ids,
                "user_params": request.user_params or {},
                "timestamp": datetime.now().isoformat()
            }
        )
        
        logger.info(f"价格计算任务已发布到队列: job_id={request.job_id}")
        
        # 立即返回
        return {
            "status": "accepted",
            "message": "价格计算任务已提交到队列，请通过 WebSocket 监听进度",
            "job_id": request.job_id,
            "subgraph_count": len(request.subgraph_ids)
        }
        
    except Exception as e:
        logger.error(f"提交价格计算任务失败: {e}", exc_info=True)
        
        # 如果消息队列不可用，回退到直接执行
        logger.warning("消息队列不可用，回退到直接执行模式")
        
        try:
            # 导入必要的模块
            from agents import get_pricing_agent
            import asyncio
            
            # 获取 PricingAgent 实例
            pricing_agent = get_pricing_agent()
            
            # 创建后台任务（不等待完成）
            asyncio.create_task(_execute_pricing_calculation(
                pricing_agent=pricing_agent,
                job_id=request.job_id,
                subgraph_ids=request.subgraph_ids,
                user_params=request.user_params or {}
            ))
            
            logger.info(f"价格计算任务已提交到后台: job_id={request.job_id}")
            
            # 立即返回
            return {
                "status": "accepted",
                "message": "价格计算任务已提交（直接执行模式），请通过 WebSocket 监听进度",
                "job_id": request.job_id,
                "subgraph_count": len(request.subgraph_ids)
            }
        except Exception as fallback_error:
            logger.error(f"回退执行也失败: {fallback_error}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"提交任务失败: {str(e)}")


@router.get("/status/{job_id}")
async def get_pricing_status(job_id: str):
    """
    查询价格计算状态
    
    Args:
        job_id: 任务ID
    
    Returns:
        所有子图的价格计算状态
    """
    try:
        from shared.database import get_db
        from shared.models import Subgraph
        from sqlalchemy import select, text
        
        async for db in get_db():
            # 查询所有子图及其价格
            # 注意：这里假设有 pricing_results 表，实际表名可能不同
            query = text("""
                SELECT 
                    s.subgraph_id,
                    s.part_code,
                    pr.total_cost,
                    pr.material_cost,
                    pr.nc_cost,
                    pr.wire_cost,
                    pr.created_at
                FROM subgraphs s
                LEFT JOIN pricing_results pr ON s.subgraph_id = pr.subgraph_id
                WHERE s.job_id = :job_id
                ORDER BY s.part_code
            """)
            
            result = await db.execute(query, {"job_id": job_id})
            rows = result.fetchall()
            
            subgraphs_data = []
            total_cost = 0.0
            
            for row in rows:
                has_pricing = row.total_cost is not None
                if has_pricing:
                    total_cost += row.total_cost
                
                subgraphs_data.append({
                    "subgraph_id": row.subgraph_id,
                    "part_code": row.part_code,
                    "has_pricing": has_pricing,
                    "pricing": {
                        "total_cost": row.total_cost,
                        "material_cost": row.material_cost,
                        "nc_cost": row.nc_cost,
                        "wire_cost": row.wire_cost,
                        "calculated_at": row.created_at.isoformat() if row.created_at else None
                    } if has_pricing else None
                })
            
            return {
                "status": "ok",
                "job_id": job_id,
                "total": len(subgraphs_data),
                "total_cost": total_cost,
                "subgraphs": subgraphs_data
            }
            
    except Exception as e:
        logger.error(f"查询价格状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/summary/{job_id}")
async def get_pricing_summary(job_id: str):
    """
    获取价格汇总信息
    
    Args:
        job_id: 任务ID
    
    Returns:
        价格汇总统计
    """
    try:
        from shared.database import get_db
        from sqlalchemy import text
        
        async for db in get_db():
            query = text("""
                SELECT 
                    COUNT(*) as total_subgraphs,
                    COUNT(pr.subgraph_id) as priced_subgraphs,
                    SUM(pr.total_cost) as total_cost,
                    SUM(pr.material_cost) as total_material_cost,
                    SUM(pr.nc_cost) as total_nc_cost,
                    SUM(pr.wire_cost) as total_wire_cost
                FROM subgraphs s
                LEFT JOIN pricing_results pr ON s.subgraph_id = pr.subgraph_id
                WHERE s.job_id = :job_id
            """)
            
            result = await db.execute(query, {"job_id": job_id})
            row = result.fetchone()
            
            return {
                "status": "ok",
                "job_id": job_id,
                "summary": {
                    "total_subgraphs": row.total_subgraphs,
                    "priced_subgraphs": row.priced_subgraphs,
                    "pending_subgraphs": row.total_subgraphs - row.priced_subgraphs,
                    "total_cost": float(row.total_cost) if row.total_cost else 0.0,
                    "breakdown": {
                        "material_cost": float(row.total_material_cost) if row.total_material_cost else 0.0,
                        "nc_cost": float(row.total_nc_cost) if row.total_nc_cost else 0.0,
                        "wire_cost": float(row.total_wire_cost) if row.total_wire_cost else 0.0
                    }
                }
            }
            
    except Exception as e:
        logger.error(f"获取价格汇总失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
