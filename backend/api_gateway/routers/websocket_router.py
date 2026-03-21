"""
WebSocket路由
负责人：ZZH
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..websocket import manager
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """
    WebSocket连接端点
    
    连接URL: ws://localhost:8000/ws/{job_id}
    
    Args:
        job_id: 任务ID
    """
    await manager.connect(websocket, job_id)
    
    try:
        # 发送欢迎消息
        welcome_message = {
            "type": "connected",
            "job_id": job_id,
            "timestamp": datetime.now().isoformat(),
            "message": "WebSocket连接已建立",
            "data": {
                "connection_count": manager.get_connection_count(job_id)
            }
        }
        await websocket.send_json(welcome_message)
        logger.info(f"📨 欢迎消息已发送: job_id={job_id}")
        
        # 保持连接，接收客户端消息
        while True:
            # 接收文本消息
            data = await websocket.receive_text()
            
            # 尝试解析JSON
            try:
                message = json.loads(data)
                message_type = message.get("type", "unknown")
                
                # 处理不同类型的消息
                if message_type == "pong":
                    # 心跳响应（DEBUG 级别，避免刷屏）
                    logger.debug(f"💓 收到心跳响应: job_id={job_id}")
                elif message_type == "ping":
                    # 客户端主动ping（DEBUG 级别，避免刷屏）
                    logger.debug(f"📥 收到 ping: job_id={job_id}, sequence={message.get('sequence')}")
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    # 其他消息类型才记录 INFO 日志
                    logger.info(f"📥 收到客户端消息: job_id={job_id}, type={message_type}, data={data}")
                    
                    # 回显消息（测试用）
                    echo_message = {
                        "type": "echo",
                        "job_id": job_id,
                        "timestamp": datetime.now().isoformat(),
                        "data": message
                    }
                    await websocket.send_json(echo_message)
                    logger.info(f"🔄 回显消息: job_id={job_id}")
            
            except json.JSONDecodeError:
                # 如果不是JSON，直接回显文本
                logger.info(f"📥 收到非JSON消息: job_id={job_id}, data={data}")
                await websocket.send_json({
                    "type": "echo",
                    "job_id": job_id,
                    "timestamp": datetime.now().isoformat(),
                    "data": data
                })
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
        logger.info(f"🔌 客户端主动断开连接: job_id={job_id}")
    
    except Exception as e:
        logger.error(f"❌ WebSocket错误: job_id={job_id}, error={e}")
        manager.disconnect(websocket, job_id)


@router.get("/ws/{job_id}/history")
async def get_message_history(job_id: str):
    """
    获取消息历史（用于断线重连）
    
    Returns:
        最近10条消息
    """
    from ..utils.redis_client import redis_client
    
    try:
        key = f"job:{job_id}:messages"
        messages = await redis_client.lrange(key, 0, -1)
        
        return {
            "job_id": job_id,
            "count": len(messages),
            "messages": [json.loads(m) for m in messages]
        }
    except Exception as e:
        logger.error(f"❌ 获取消息历史失败: {e}")
        return {
            "job_id": job_id,
            "count": 0,
            "messages": [],
            "error": str(e)
        }


@router.get("/ws/status")
async def websocket_status():
    """
    获取WebSocket连接状态
    
    Returns:
        连接统计信息
    """
    return {
        "total_connections": manager.get_connection_count(),
        "active_jobs": manager.get_all_job_ids(),
        "job_details": {
            job_id: manager.get_connection_count(job_id)
            for job_id in manager.get_all_job_ids()
        }
    }
