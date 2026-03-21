"""
交互路由
负责人：ZZH
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.interaction_models import UserResponse
from ..services.interaction_service import InteractionService
from ..repositories.interaction_repository import InteractionRepository
from ..auth import get_current_user
from shared.database import get_db
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/jobs", tags=["interactions"])

@router.post("/{job_id}/submit")
async def submit_user_input(
    job_id: str,
    response: UserResponse,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    用户提交输入
    
    请求体示例:
    ```json
    {
        "card_id": "uuid",
        "action": "submit",
        "inputs": {
            "UP01.thickness_mm": 10,
            "UP02.thickness_mm": 15
        }
    }
    ```
    
    Returns:
        提交结果
    """
    logger.info(f"📥 收到用户提交: job_id={job_id}, card_id={response.card_id}, action={response.action}")
    
    service = InteractionService()
    
    try:
        async with db.begin():
            result = await service.handle_user_response(
                db=db,
                job_id=job_id,
                response=response
            )
        
        # TODO: 发送消息到RabbitMQ，恢复工作流
        # 这部分由ZQY的OrchestratorAgent处理
        # from ..utils.rabbitmq_client import rabbitmq_client
        # await rabbitmq_client.send_message(
        #     queue="job_resume",
        #     message={
        #         "job_id": job_id,
        #         "action": "resume",
        #         "user_inputs": result["inputs"]
        #     }
        # )
        
        logger.info(f"✅ 用户提交处理成功: job_id={job_id}")
        
        return {
            "success": True,
            "message": "用户输入已提交",
            "data": result
        }
    
    except ValueError as e:
        logger.error(f"❌ 参数验证失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@router.get("/{job_id}/interactions")
async def get_interactions(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取任务的所有交互记录
    
    Returns:
        交互记录列表
    """
    repo = InteractionRepository()
    interactions = await repo.get_all_interactions(db, job_id)
    
    return {
        "job_id": job_id,
        "count": len(interactions),
        "interactions": [
            {
                "interaction_id": row.interaction_id,
                "card_id": row.card_id,
                "card_type": row.card_type,
                "status": row.status,
                "action": row.action,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "responded_at": row.responded_at.isoformat() if row.responded_at else None
            }
            for row in interactions
        ]
    }

@router.get("/{job_id}/interactions/pending")
async def get_pending_interactions(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取待处理的交互
    
    Returns:
        待处理的交互记录列表
    """
    repo = InteractionRepository()
    interactions = await repo.get_pending_interactions(db, job_id)
    
    return {
        "job_id": job_id,
        "count": len(interactions),
        "interactions": [dict(row) for row in interactions]
    }
