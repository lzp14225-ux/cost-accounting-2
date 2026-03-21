"""
Clarification Models - 输入澄清数据模型
负责人：人员B2

职责：
定义输入澄清功能所需的所有数据模型和类型
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


# ========== 枚举类型 ==========

class ResponseType(str, Enum):
    """用户响应类型"""
    CONFIRM = "confirm"
    REJECT = "reject"
    MODIFY = "modify"


class ValidationIssueType(str, Enum):
    """验证问题类型"""
    MISSING_FIELD = "missing_field"
    INVALID_VALUE = "invalid_value"
    AMBIGUOUS = "ambiguous"
    INCOMPLETE = "incomplete"
    UNKNOWN_PART_CODE = "unknown_part_code"
    UNKNOWN_FIELD = "unknown_field"


class ValidationSeverity(str, Enum):
    """验证问题严重程度"""
    ERROR = "error"
    WARNING = "warning"


class DataSource(str, Enum):
    """数据来源"""
    PROCESS_MAPPING = "process_mapping"
    DISPLAY_VIEW = "display_view"
    NONE = "none"


# ========== 数据模型 ==========

@dataclass
class ValidationIssue:
    """验证问题"""
    type: ValidationIssueType
    field: Optional[str]
    message: str
    severity: ValidationSeverity
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "field": self.field,
            "message": self.message,
            "severity": self.severity.value
        }


@dataclass
class ValueValidationResult:
    """值验证结果"""
    is_valid: bool
    matched_value: Optional[str]  # 标准化后的值
    source: DataSource  # 数据来源
    alternatives: List[str] = field(default_factory=list)  # 可能的替代值
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "matched_value": self.matched_value,
            "source": self.source.value,
            "alternatives": self.alternatives,
            "confidence": self.confidence
        }


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    extracted_entities: Dict[str, Any]
    issues: List[ValidationIssue] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "extracted_entities": self.extracted_entities,
            "issues": [issue.to_dict() for issue in self.issues],
            "suggestions": self.suggestions
        }


@dataclass
class ResponseOption:
    """响应选项"""
    type: ResponseType
    label: str  # 显示文本
    action: str  # 前端触发的动作
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "label": self.label,
            "action": self.action
        }


@dataclass
class ConfirmationMessage:
    """确认消息"""
    message_text: str
    parsed_interpretation: Dict[str, Any]
    options: List[ResponseOption]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_text": self.message_text,
            "parsed_interpretation": self.parsed_interpretation,
            "options": [opt.to_dict() for opt in self.options]
        }


@dataclass
class ClarificationResult:
    """澄清处理结果"""
    needs_clarification: bool
    confidence_score: float
    parsed_entities: Dict[str, Any]
    confirmation_message: Optional[str] = None
    normalized_input: Optional[str] = None
    clarification_id: Optional[str] = None
    validation_result: Optional[ValidationResult] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "needs_clarification": self.needs_clarification,
            "confidence_score": self.confidence_score,
            "parsed_entities": self.parsed_entities,
            "confirmation_message": self.confirmation_message,
            "normalized_input": self.normalized_input,
            "clarification_id": self.clarification_id
        }
        if self.validation_result:
            result["validation_result"] = self.validation_result.to_dict()
        return result


@dataclass
class HistoryEntry:
    """历史记录条目"""
    timestamp: datetime
    original_input: str
    normalized_input: str
    parsed_entities: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "original_input": self.original_input,
            "normalized_input": self.normalized_input,
            "parsed_entities": self.parsed_entities
        }


@dataclass
class HistoryMatch:
    """历史匹配结果"""
    entry: HistoryEntry
    similarity: float  # 0.0 - 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "similarity": self.similarity
        }


@dataclass
class ResponseResult:
    """响应处理结果"""
    success: bool
    normalized_input: Optional[str] = None
    error_message: Optional[str] = None
    requires_new_clarification: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "normalized_input": self.normalized_input,
            "error_message": self.error_message,
            "requires_new_clarification": self.requires_new_clarification
        }


# ========== 辅助函数 ==========

def create_default_response_options() -> List[ResponseOption]:
    """创建默认的三个响应选项"""
    return [
        ResponseOption(
            type=ResponseType.CONFIRM,
            label="确认",
            action="confirm_clarification"
        ),
        ResponseOption(
            type=ResponseType.REJECT,
            label="拒绝",
            action="reject_clarification"
        ),
        ResponseOption(
            type=ResponseType.MODIFY,
            label="修改",
            action="modify_clarification"
        )
    ]
