"""
LLMFailureHandler - LLM 理解失败处理器
负责人：人员B2

职责：
1. 检测 LLM 低置信度
2. 生成理解失败提示
3. 处理连续失败
4. 提供用户友好的建议
"""
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class FailureReason(str, Enum):
    """失败原因"""
    LOW_CONFIDENCE = "low_confidence"  # 置信度过低
    AMBIGUOUS_INPUT = "ambiguous_input"  # 输入模糊
    MISSING_CONTEXT = "missing_context"  # 缺少上下文
    INVALID_FORMAT = "invalid_format"  # 格式无效
    UNKNOWN = "unknown"  # 未知原因


@dataclass
class FailureEvent:
    """失败事件"""
    timestamp: datetime
    reason: FailureReason
    user_input: str
    confidence: float
    session_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureSuggestion:
    """失败建议"""
    reason: FailureReason
    message: str
    examples: List[str]
    tips: List[str]


class LLMFailureHandler:
    """LLM 理解失败处理器"""
    
    def __init__(self):
        """初始化失败处理器"""
        # 配置参数
        self.confidence_threshold = 0.5  # 置信度阈值
        self.consecutive_failure_threshold = 3  # 连续失败阈值
        self.failure_window = 300  # 失败窗口（秒）
        
        # 失败记录
        self.failure_history: Dict[str, List[FailureEvent]] = {}  # session_id -> events
        
        logger.info("✅ LLMFailureHandler 初始化完成")
    
    def check_confidence(
        self,
        confidence: float,
        user_input: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, Optional[FailureSuggestion]]:
        """
        检查置信度是否过低
        
        Args:
            confidence: LLM 返回的置信度
            user_input: 用户输入
            session_id: 会话ID
            context: 上下文信息
        
        Returns:
            (是否失败, 失败建议)
        """
        if confidence >= self.confidence_threshold:
            return False, None
        
        logger.warning(f"⚠️  LLM 置信度过低: {confidence:.2f} < {self.confidence_threshold}")
        
        # 记录失败事件
        reason = self._analyze_failure_reason(confidence, user_input, context)
        self._record_failure(session_id, reason, user_input, confidence)
        
        # 生成建议
        suggestion = self._generate_suggestion(reason, user_input, session_id)
        
        return True, suggestion
    
    def _analyze_failure_reason(
        self,
        confidence: float,
        user_input: str,
        context: Optional[Dict[str, Any]]
    ) -> FailureReason:
        """分析失败原因"""
        # 置信度极低 → 完全无法理解
        if confidence < 0.3:
            return FailureReason.AMBIGUOUS_INPUT
        
        # 输入过短 → 缺少上下文
        if len(user_input.strip()) < 5:
            return FailureReason.MISSING_CONTEXT
        
        # 包含特殊字符或格式错误
        if any(char in user_input for char in ['@', '#', '$', '%', '^', '&', '*']):
            return FailureReason.INVALID_FORMAT
        
        # 默认：置信度过低
        return FailureReason.LOW_CONFIDENCE
    
    def _record_failure(
        self,
        session_id: str,
        reason: FailureReason,
        user_input: str,
        confidence: float
    ):
        """记录失败事件"""
        event = FailureEvent(
            timestamp=datetime.now(),
            reason=reason,
            user_input=user_input,
            confidence=confidence,
            session_id=session_id
        )
        
        if session_id not in self.failure_history:
            self.failure_history[session_id] = []
        
        self.failure_history[session_id].append(event)
        
        # 清理过期事件
        self._cleanup_old_events(session_id)
    
    def _cleanup_old_events(self, session_id: str):
        """清理过期事件"""
        if session_id not in self.failure_history:
            return
        
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.failure_window)
        
        self.failure_history[session_id] = [
            event for event in self.failure_history[session_id]
            if event.timestamp > cutoff
        ]
    
    def _generate_suggestion(
        self,
        reason: FailureReason,
        user_input: str,
        session_id: str
    ) -> FailureSuggestion:
        """生成失败建议"""
        # 检查是否连续失败
        consecutive_failures = self._count_consecutive_failures(session_id)
        
        if consecutive_failures >= self.consecutive_failure_threshold:
            return self._generate_special_suggestion(reason, consecutive_failures)
        
        # 根据失败原因生成建议
        if reason == FailureReason.LOW_CONFIDENCE:
            return FailureSuggestion(
                reason=reason,
                message="无法准确理解您的意图，请尝试更明确的表达",
                examples=[
                    "✅ 正确示例：\"将 B2-05 的材质改为 718\"",
                    "✅ 正确示例：\"b205 工艺改为慢丝割一修一\"",
                    "✅ 正确示例：\"材质为 45# 的零件改为 CR12\""
                ],
                tips=[
                    "明确指定零件ID或筛选条件",
                    "使用完整的字段名称（如\"材质\"、\"工艺\"）",
                    "避免使用过于简略的表达"
                ]
            )
        
        elif reason == FailureReason.AMBIGUOUS_INPUT:
            return FailureSuggestion(
                reason=reason,
                message="您的输入过于模糊，系统无法理解",
                examples=[
                    "❌ 错误示例：\"改一下\"",
                    "✅ 正确示例：\"将 B2-05 的材质改为 718\"",
                    "❌ 错误示例：\"那个改成这个\"",
                    "✅ 正确示例：\"将上模板的工艺改为慢丝割一修一\""
                ],
                tips=[
                    "明确说明要修改哪个零件",
                    "明确说明要修改什么字段",
                    "明确说明要改成什么值"
                ]
            )
        
        elif reason == FailureReason.MISSING_CONTEXT:
            return FailureSuggestion(
                reason=reason,
                message="输入信息不足，请提供更多细节",
                examples=[
                    "❌ 错误示例：\"改\"",
                    "✅ 正确示例：\"将 B2-05 的材质改为 718\"",
                    "❌ 错误示例：\"718\"",
                    "✅ 正确示例：\"材质改为 718\""
                ],
                tips=[
                    "完整描述您的修改需求",
                    "包含零件标识、字段名称和新值",
                    "可以参考历史成功的输入格式"
                ]
            )
        
        elif reason == FailureReason.INVALID_FORMAT:
            return FailureSuggestion(
                reason=reason,
                message="输入格式不正确，请检查后重试",
                examples=[
                    "✅ 支持的格式：\"零件ID + 字段 + 改为 + 新值\"",
                    "✅ 示例：\"B2-05 材质改为 718\"",
                    "✅ 示例：\"b205 工艺改为慢丝割一修一\""
                ],
                tips=[
                    "避免使用特殊符号",
                    "使用中文或英文描述",
                    "参考系统提供的示例格式"
                ]
            )
        
        else:
            return FailureSuggestion(
                reason=reason,
                message="系统无法理解您的输入，请重新表达",
                examples=[
                    "✅ 示例：\"将 B2-05 的材质改为 718\"",
                    "✅ 示例：\"b205 工艺改为慢丝割一修一\""
                ],
                tips=[
                    "使用清晰明确的表达",
                    "参考系统提供的示例"
                ]
            )
    
    def _count_consecutive_failures(self, session_id: str) -> int:
        """统计连续失败次数"""
        if session_id not in self.failure_history:
            return 0
        
        events = self.failure_history[session_id]
        if not events:
            return 0
        
        # 从最近的事件开始倒数
        count = 0
        for event in reversed(events):
            count += 1
        
        return count
    
    def _generate_special_suggestion(
        self,
        reason: FailureReason,
        consecutive_failures: int
    ) -> FailureSuggestion:
        """生成连续失败的特殊建议"""
        return FailureSuggestion(
            reason=reason,
            message=f"您已连续 {consecutive_failures} 次输入失败，建议：",
            examples=[
                "📋 使用标准格式：\"零件ID + 字段 + 改为 + 新值\"",
                "✅ 示例1：\"B2-05 材质改为 718\"",
                "✅ 示例2：\"b205 工艺改为慢丝割一修一\"",
                "✅ 示例3：\"材质为 45# 的零件改为 CR12\"",
                "✅ 示例4：\"尺寸为 200*150*30 的零件材质改为 718\""
            ],
            tips=[
                "🔍 检查零件ID是否正确（如 B2-05, DIE-03）",
                "📝 使用完整的字段名称（材质、工艺、尺寸等）",
                "💡 可以使用筛选条件（如\"材质为 45#\"）",
                "❓ 如仍有问题，请联系管理员获取帮助"
            ]
        )
    
    def reset_failures(self, session_id: str):
        """重置失败计数"""
        if session_id in self.failure_history:
            self.failure_history[session_id] = []
            logger.info(f"✅ 已重置会话 {session_id} 的失败计数")
    
    def get_failure_stats(self, session_id: str) -> Dict[str, Any]:
        """获取失败统计"""
        if session_id not in self.failure_history:
            return {
                "total_failures": 0,
                "consecutive_failures": 0,
                "recent_events": []
            }
        
        events = self.failure_history[session_id]
        
        return {
            "total_failures": len(events),
            "consecutive_failures": self._count_consecutive_failures(session_id),
            "recent_events": [
                {
                    "timestamp": event.timestamp.isoformat(),
                    "reason": event.reason,
                    "user_input": event.user_input,
                    "confidence": event.confidence
                }
                for event in events[-5:]  # 最近5个事件
            ]
        }
    
    def format_suggestion_message(self, suggestion: FailureSuggestion) -> str:
        """格式化建议消息（用于前端显示）"""
        lines = [suggestion.message, ""]
        
        if suggestion.examples:
            lines.append("📋 示例：")
            for example in suggestion.examples:
                lines.append(f"  {example}")
            lines.append("")
        
        if suggestion.tips:
            lines.append("💡 建议：")
            for tip in suggestion.tips:
                lines.append(f"  • {tip}")
        
        return "\n".join(lines)


# 全局单例
_llm_failure_handler: Optional[LLMFailureHandler] = None


def get_llm_failure_handler() -> LLMFailureHandler:
    """获取全局 LLM 失败处理器"""
    global _llm_failure_handler
    if _llm_failure_handler is None:
        _llm_failure_handler = LLMFailureHandler()
    return _llm_failure_handler
