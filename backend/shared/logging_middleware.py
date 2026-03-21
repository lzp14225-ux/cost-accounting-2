"""
日志中间件
负责自动记录 API 请求、响应等关键信息

功能：
1. 记录 API 请求（IP、路径、方法、参数）
2. 记录响应状态和耗时
3. 自动添加 trace_id
4. 敏感信息脱敏
"""
import time
import uuid
import json
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from shared.logging_config import get_logger, LogContext

logger = get_logger(__name__)


# 敏感字段列表（需要脱敏）
SENSITIVE_FIELDS = {
    "password", "token", "secret", "api_key", "access_token", 
    "refresh_token", "authorization", "jwt", "credential"
}


def mask_sensitive_data(data: dict) -> dict:
    """
    脱敏敏感信息
    
    Args:
        data: 原始数据
    
    Returns:
        脱敏后的数据
    """
    if not isinstance(data, dict):
        return data
    
    masked = {}
    for key, value in data.items():
        key_lower = key.lower()
        
        # 检查是否为敏感字段
        if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
            masked[key] = "***MASKED***"
        elif isinstance(value, dict):
            masked[key] = mask_sensitive_data(value)
        elif isinstance(value, list):
            masked[key] = [mask_sensitive_data(item) if isinstance(item, dict) else item for item in value]
        else:
            masked[key] = value
    
    return masked


def get_client_ip(request: Request) -> str:
    """
    获取客户端真实 IP
    
    优先级：
    1. X-Forwarded-For（代理）
    2. X-Real-IP（Nginx）
    3. request.client.host（直连）
    """
    # 检查代理头
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # 检查 Nginx 头
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # 直连 IP
    if request.client:
        return request.client.host
    
    return "unknown"


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    日志中间件
    
    自动记录所有 API 请求和响应
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求"""
        # 生成 trace_id
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        
        # 获取客户端 IP
        client_ip = get_client_ip(request)
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 使用日志上下文
        with LogContext(trace_id=trace_id):
            # 记录请求信息
            await self._log_request(request, client_ip)
            
            # 处理请求
            try:
                response = await call_next(request)
                
                # 计算耗时
                elapsed = time.time() - start_time
                
                # 记录响应信息
                self._log_response(request, response, elapsed, client_ip)
                
                # 添加 trace_id 到响应头
                response.headers["X-Trace-ID"] = trace_id
                
                return response
            
            except Exception as e:
                # 记录异常
                elapsed = time.time() - start_time
                logger.error(
                    f"❌ 请求异常: {request.method} {request.url.path} | "
                    f"IP={client_ip} | 耗时={elapsed:.3f}s | 错误={str(e)}",
                    exc_info=True
                )
                raise
    
    async def _log_request(self, request: Request, client_ip: str):
        """记录请求信息"""
        # 获取请求参数
        query_params = dict(request.query_params)
        
        # 获取 Content-Type
        content_type = request.headers.get("content-type", "").lower()
        
        # 获取请求体（仅 POST/PUT/PATCH，且非文件上传）
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            # 跳过文件上传请求（multipart/form-data）
            if "multipart/form-data" in content_type:
                body = "<文件上传>"
            else:
                try:
                    # 读取请求体
                    body_bytes = await request.body()
                    if body_bytes:
                        body = json.loads(body_bytes)
                        # 脱敏
                        body = mask_sensitive_data(body)
                except Exception:
                    body = "<无法解析>"
        
        # 记录日志
        log_parts = [
            f"📨 收到请求: {request.method} {request.url.path}",
            f"IP={client_ip}"
        ]
        
        if query_params:
            log_parts.append(f"Query={mask_sensitive_data(query_params)}")
        
        if body:
            # 限制 body 长度
            body_str = json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else str(body)
            if len(body_str) > 500:
                body_str = body_str[:500] + "..."
            log_parts.append(f"Body={body_str}")
        
        logger.info(" | ".join(log_parts))
    
    def _log_response(self, request: Request, response: Response, elapsed: float, client_ip: str):
        """记录响应信息"""
        status_code = response.status_code
        
        # 根据状态码选择日志级别和 emoji
        if status_code < 400:
            emoji = "✅"
            log_func = logger.info
        elif status_code < 500:
            emoji = "⚠️"
            log_func = logger.warning
        else:
            emoji = "❌"
            log_func = logger.error
        
        log_func(
            f"{emoji} 响应完成: {request.method} {request.url.path} | "
            f"状态={status_code} | IP={client_ip} | 耗时={elapsed:.3f}s"
        )


# ========== 工具函数：用于手动记录关键操作 ==========

def log_rabbitmq_publish(queue: str, message: dict, success: bool = True):
    """
    记录 RabbitMQ 消息发送
    
    Args:
        queue: 队列名
        message: 消息内容
        success: 是否成功
    """
    # 脱敏
    masked_message = mask_sensitive_data(message)
    
    # 限制长度
    message_str = json.dumps(masked_message, ensure_ascii=False)
    if len(message_str) > 300:
        message_str = message_str[:300] + "..."
    
    if success:
        logger.info(f"📤 发送消息到队列: {queue} | 内容={message_str}")
    else:
        logger.error(f"❌ 发送消息失败: {queue} | 内容={message_str}")


def log_rabbitmq_consume(queue: str, message: dict):
    """
    记录 RabbitMQ 消息消费
    
    Args:
        queue: 队列名
        message: 消息内容
    """
    # 脱敏
    masked_message = mask_sensitive_data(message)
    
    # 限制长度
    message_str = json.dumps(masked_message, ensure_ascii=False)
    if len(message_str) > 300:
        message_str = message_str[:300] + "..."
    
    logger.info(f"📨 从队列接收消息: {queue} | 内容={message_str}")


def log_redis_operation(operation: str, key: str, value: any = None, success: bool = True):
    """
    记录 Redis 操作
    
    Args:
        operation: 操作类型（set, get, delete, publish 等）
        key: Redis key
        value: 值（可选）
        success: 是否成功
    """
    log_parts = [f"💾 Redis {operation.upper()}: key={key}"]
    
    # 记录值（脱敏 + 限制长度）
    if value is not None:
        if isinstance(value, dict):
            value = mask_sensitive_data(value)
        
        value_str = str(value)
        if len(value_str) > 200:
            value_str = value_str[:200] + "..."
        
        log_parts.append(f"value={value_str}")
    
    if success:
        logger.debug(" | ".join(log_parts))
    else:
        logger.error(f"❌ Redis 操作失败: {' | '.join(log_parts)}")


def log_websocket_message(connection_id: str, message_type: str, data: dict = None, direction: str = "send"):
    """
    记录 WebSocket 消息
    
    Args:
        connection_id: 连接 ID（通常是 job_id 或 user_id）
        message_type: 消息类型
        data: 消息数据（可选）
        direction: 方向（send 或 receive）
    """
    emoji = "📤" if direction == "send" else "📨"
    
    log_parts = [
        f"{emoji} WebSocket {direction.upper()}: conn={connection_id}",
        f"type={message_type}"
    ]
    
    # 记录数据摘要
    if data:
        # 脱敏
        masked_data = mask_sensitive_data(data)
        
        # 只记录关键字段或长度
        if isinstance(masked_data, dict):
            if len(masked_data) > 5:
                log_parts.append(f"fields={list(masked_data.keys())[:5]}")
            else:
                data_str = json.dumps(masked_data, ensure_ascii=False)
                if len(data_str) > 200:
                    data_str = data_str[:200] + "..."
                log_parts.append(f"data={data_str}")
        elif isinstance(masked_data, list):
            log_parts.append(f"count={len(masked_data)}")
    
    logger.info(" | ".join(log_parts))


def log_database_operation(operation: str, table: str = None, affected_rows: int = None, elapsed: float = None):
    """
    记录数据库操作
    
    Args:
        operation: 操作类型（SELECT, INSERT, UPDATE, DELETE）
        table: 表名（可选）
        affected_rows: 影响行数（可选）
        elapsed: 耗时（秒）
    """
    log_parts = [f"🗄️  数据库 {operation.upper()}"]
    
    if table:
        log_parts.append(f"table={table}")
    
    if affected_rows is not None:
        log_parts.append(f"rows={affected_rows}")
    
    if elapsed is not None:
        log_parts.append(f"耗时={elapsed:.3f}s")
    
    logger.debug(" | ".join(log_parts))
