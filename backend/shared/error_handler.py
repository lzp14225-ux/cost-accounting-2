"""
ErrorHandler - 统一错误处理与降级管理器
负责人：人员B2

职责：
1. 统一的错误处理逻辑
2. 降级策略管理
3. 错误日志记录
4. 降级事件追踪
"""
import logging
import time
from typing import Optional, Dict, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DegradationLevel(str, Enum):
    """降级级别"""
    NORMAL = "normal"  # 正常运行
    PARTIAL = "partial"  # 部分降级（如 LLM 不可用，使用规则）
    MINIMAL = "minimal"  # 最小功能（仅精确匹配）
    UNAVAILABLE = "unavailable"  # 服务不可用


class ErrorType(str, Enum):
    """错误类型"""
    TIMEOUT = "timeout"  # 超时
    LLM_UNAVAILABLE = "llm_unavailable"  # LLM 服务不可用
    MATCH_TIMEOUT = "match_timeout"  # 匹配超时
    CONTEXT_EXPIRED = "context_expired"  # 上下文过期
    INVALID_INPUT = "invalid_input"  # 无效输入
    DATABASE_ERROR = "database_error"  # 数据库错误
    REDIS_ERROR = "redis_error"  # Redis 错误
    UNKNOWN = "unknown"  # 未知错误


@dataclass
class DegradationEvent:
    """降级事件"""
    timestamp: datetime
    error_type: ErrorType
    from_level: DegradationLevel
    to_level: DegradationLevel
    component: str
    error_message: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ErrorHandler:
    """统一错误处理器"""
    
    def __init__(self):
        """初始化错误处理器"""
        self.current_level = DegradationLevel.NORMAL
        self.degradation_history: list[DegradationEvent] = []
        self.error_counts: Dict[ErrorType, int] = {}
        self.last_error_time: Dict[ErrorType, datetime] = {}
        
        # 配置参数
        self.max_errors_per_minute = 10  # 每分钟最大错误数
        self.degradation_threshold = 3  # 连续错误阈值
        self.recovery_time = 60  # 恢复时间（秒）
        
        logger.info("✅ ErrorHandler 初始化完成")
    
    def handle_error(
        self,
        error: Exception,
        error_type: ErrorType,
        component: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        处理错误并返回降级策略
        
        Args:
            error: 异常对象
            error_type: 错误类型
            component: 组件名称
            context: 上下文信息
        
        Returns:
            降级策略字典
        """
        logger.error(f"❌ {component} 错误: {error_type.value} - {str(error)}")
        
        # 记录错误
        self._record_error(error_type)
        
        # 判断是否需要降级
        should_degrade, new_level = self._should_degrade(error_type, component)
        
        if should_degrade and new_level != self.current_level:
            self._degrade(error_type, new_level, component, str(error), context or {})
        
        # 返回降级策略
        return {
            "degradation_level": self.current_level,
            "error_type": error_type,
            "should_retry": self._should_retry(error_type),
            "fallback_strategy": self._get_fallback_strategy(error_type, component),
            "user_message": self._get_user_message(error_type, component)
        }
    
    def _record_error(self, error_type: ErrorType):
        """记录错误"""
        now = datetime.now()
        
        # 更新错误计数
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        self.last_error_time[error_type] = now
        
        # 清理过期的错误计数（1分钟前的）
        for et in list(self.error_counts.keys()):
            last_time = self.last_error_time.get(et)
            if last_time and (now - last_time).total_seconds() > 60:
                self.error_counts[et] = 0
    
    def _should_degrade(
        self,
        error_type: ErrorType,
        component: str
    ) -> tuple[bool, DegradationLevel]:
        """
        判断是否需要降级
        
        Returns:
            (是否降级, 新的降级级别)
        """
        error_count = self.error_counts.get(error_type, 0)
        
        # LLM 不可用 → 部分降级
        if error_type == ErrorType.LLM_UNAVAILABLE:
            if error_count >= 2:
                return True, DegradationLevel.PARTIAL
        
        # 匹配超时 → 最小功能
        elif error_type == ErrorType.MATCH_TIMEOUT:
            if error_count >= self.degradation_threshold:
                return True, DegradationLevel.MINIMAL
        
        # 数据库错误 → 服务不可用
        elif error_type == ErrorType.DATABASE_ERROR:
            if error_count >= 3:
                return True, DegradationLevel.UNAVAILABLE
        
        # Redis 错误 → 部分降级（不影响核心功能）
        elif error_type == ErrorType.REDIS_ERROR:
            if error_count >= 5:
                return True, DegradationLevel.PARTIAL
        
        return False, self.current_level
    
    def _degrade(
        self,
        error_type: ErrorType,
        new_level: DegradationLevel,
        component: str,
        error_message: str,
        metadata: Dict[str, Any]
    ):
        """执行降级"""
        old_level = self.current_level
        self.current_level = new_level
        
        # 记录降级事件
        event = DegradationEvent(
            timestamp=datetime.now(),
            error_type=error_type,
            from_level=old_level,
            to_level=new_level,
            component=component,
            error_message=error_message,
            metadata=metadata
        )
        self.degradation_history.append(event)
        
        logger.warning(
            f"⚠️  系统降级: {old_level.value} → {new_level.value} "
            f"(原因: {error_type.value}, 组件: {component})"
        )
    
    def _should_retry(self, error_type: ErrorType) -> bool:
        """判断是否应该重试"""
        # 超时错误不重试
        if error_type in [ErrorType.TIMEOUT, ErrorType.MATCH_TIMEOUT]:
            return False
        
        # 上下文过期不重试
        if error_type == ErrorType.CONTEXT_EXPIRED:
            return False
        
        # 无效输入不重试
        if error_type == ErrorType.INVALID_INPUT:
            return False
        
        # 其他错误可以重试
        return True
    
    def _get_fallback_strategy(
        self,
        error_type: ErrorType,
        component: str
    ) -> Dict[str, Any]:
        """
        获取降级策略
        
        Returns:
            降级策略字典
        """
        if error_type == ErrorType.LLM_UNAVAILABLE:
            return {
                "strategy": "use_rules",
                "description": "使用规则解析代替 LLM",
                "limitations": ["功能受限", "准确性降低"]
            }
        
        elif error_type == ErrorType.MATCH_TIMEOUT:
            return {
                "strategy": "exact_match_only",
                "description": "仅使用精确匹配",
                "limitations": ["不支持模糊匹配", "不支持扩展字段匹配"]
            }
        
        elif error_type == ErrorType.CONTEXT_EXPIRED:
            return {
                "strategy": "request_resubmit",
                "description": "请求用户重新提交",
                "limitations": ["需要用户重新输入"]
            }
        
        elif error_type == ErrorType.REDIS_ERROR:
            return {
                "strategy": "skip_cache",
                "description": "跳过缓存，直接查询数据库",
                "limitations": ["性能降低"]
            }
        
        else:
            return {
                "strategy": "default",
                "description": "使用默认处理",
                "limitations": []
            }
    
    def _get_user_message(
        self,
        error_type: ErrorType,
        component: str
    ) -> str:
        """获取用户友好的错误消息"""
        if error_type == ErrorType.LLM_UNAVAILABLE:
            return "智能解析服务暂时不可用，已切换到基础模式，功能可能受限"
        
        elif error_type == ErrorType.MATCH_TIMEOUT:
            return "匹配超时，已切换到精确匹配模式，请使用更精确的输入"
        
        elif error_type == ErrorType.CONTEXT_EXPIRED:
            return "确认已过期（超过5分钟），请重新输入原始指令"
        
        elif error_type == ErrorType.INVALID_INPUT:
            return "输入格式不正确，请检查后重试"
        
        elif error_type == ErrorType.DATABASE_ERROR:
            return "数据库连接失败，请稍后重试"
        
        elif error_type == ErrorType.REDIS_ERROR:
            return "缓存服务异常，功能正常但响应可能较慢"
        
        else:
            return "系统遇到错误，请稍后重试"
    
    def try_recover(self) -> bool:
        """
        尝试恢复到正常状态
        
        Returns:
            是否成功恢复
        """
        if self.current_level == DegradationLevel.NORMAL:
            return True
        
        # 检查是否满足恢复条件
        now = datetime.now()
        can_recover = True
        
        for error_type, last_time in self.last_error_time.items():
            if (now - last_time).total_seconds() < self.recovery_time:
                can_recover = False
                break
        
        if can_recover:
            old_level = self.current_level
            self.current_level = DegradationLevel.NORMAL
            self.error_counts.clear()
            
            logger.info(f"✅ 系统已恢复: {old_level.value} → {DegradationLevel.NORMAL.value}")
            return True
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "degradation_level": self.current_level,
            "error_counts": dict(self.error_counts),
            "recent_events": [
                {
                    "timestamp": event.timestamp.isoformat(),
                    "error_type": event.error_type,
                    "from_level": event.from_level,
                    "to_level": event.to_level,
                    "component": event.component
                }
                for event in self.degradation_history[-10:]  # 最近10个事件
            ]
        }


# 全局单例
_error_handler: Optional[ErrorHandler] = None


def get_error_handler() -> ErrorHandler:
    """获取全局错误处理器"""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler


def handle_with_fallback(
    func: Callable,
    fallback_func: Callable,
    error_type: ErrorType,
    component: str,
    *args,
    **kwargs
) -> Any:
    """
    执行函数，失败时使用降级函数
    
    Args:
        func: 主函数
        fallback_func: 降级函数
        error_type: 错误类型
        component: 组件名称
        *args, **kwargs: 函数参数
    
    Returns:
        函数执行结果
    """
    error_handler = get_error_handler()
    
    try:
        return func(*args, **kwargs)
    except Exception as e:
        strategy = error_handler.handle_error(e, error_type, component)
        
        if strategy["should_retry"]:
            logger.info(f"🔄 重试 {component}...")
            try:
                return func(*args, **kwargs)
            except Exception as retry_error:
                logger.error(f"❌ 重试失败: {retry_error}")
        
        # 使用降级函数
        logger.info(f"🔄 使用降级策略: {strategy['fallback_strategy']['strategy']}")
        return fallback_func(*args, **kwargs)
