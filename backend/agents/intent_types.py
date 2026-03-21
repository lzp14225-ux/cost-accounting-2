"""
意图识别类型定义
负责人：人员B2

定义意图识别相关的数据类型和常量
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum


class IntentType(str, Enum):
    """意图类型枚举"""
    DATA_MODIFICATION = "DATA_MODIFICATION"  # 数据修改
    FEATURE_RECOGNITION = "FEATURE_RECOGNITION"  # 特征识别
    PRICE_CALCULATION = "PRICE_CALCULATION"  # 价格计算
    QUERY_DETAILS = "QUERY_DETAILS"  # 查询详情
    GENERAL_CHAT = "GENERAL_CHAT"  # 普通聊天
    WEIGHT_PRICE_CALCULATION = "WEIGHT_PRICE_CALCULATION"  # 按重量计算
    WEIGHT_PRICE_QUERY = "WEIGHT_PRICE_QUERY"  # 查询按重量计算详情
    CONFIRMATION_RESPONSE = "CONFIRMATION_RESPONSE"  # 确认响应
    UNKNOWN = "UNKNOWN"  # 未知意图


@dataclass
class IntentResult:
    """
    意图识别结果
    
    Attributes:
        intent_type: 意图类型
        confidence: 置信度 (0-1)
        parameters: 提取的参数
        raw_message: 原始消息
        reasoning: 识别推理过程（可选，用于调试）
    """
    intent_type: str
    confidence: float
    parameters: Dict[str, Any] = field(default_factory=dict)
    raw_message: str = ""
    reasoning: Optional[str] = None
    
    def __post_init__(self):
        """验证数据"""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")
        
        if self.intent_type not in [t.value for t in IntentType]:
            raise ValueError(f"Invalid intent_type: {self.intent_type}")


@dataclass
class ActionResult:
    """
    动作处理结果
    
    Attributes:
        status: 状态 (ok/error/processing)
        message: 用户友好的消息
        requires_confirmation: 是否需要用户确认
        pending_action: 待确认的操作（保存到 Redis）
        data: 结果数据
    """
    status: str
    message: str
    requires_confirmation: bool = False
    pending_action: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """验证数据"""
        if self.status not in ["ok", "error", "processing"]:
            raise ValueError(f"Invalid status: {self.status}")
        
        if self.requires_confirmation and not self.pending_action:
            raise ValueError("pending_action is required when requires_confirmation is True")


# 意图类型常量（用于快速访问）
INTENT_TYPES = {
    "DATA_MODIFICATION": IntentType.DATA_MODIFICATION,
    "FEATURE_RECOGNITION": IntentType.FEATURE_RECOGNITION,
    "PRICE_CALCULATION": IntentType.PRICE_CALCULATION,
    "QUERY_DETAILS": IntentType.QUERY_DETAILS,
    "GENERAL_CHAT": IntentType.GENERAL_CHAT,
    "WEIGHT_PRICE_CALCULATION": IntentType.WEIGHT_PRICE_CALCULATION,
    "WEIGHT_PRICE_QUERY": IntentType.WEIGHT_PRICE_QUERY,
    "CONFIRMATION_RESPONSE": IntentType.CONFIRMATION_RESPONSE,
    "UNKNOWN": IntentType.UNKNOWN,
}


# 意图关键词映射（用于规则识别）
INTENT_KEYWORDS = {
    IntentType.FEATURE_RECOGNITION: [
        "特征识别", "识别特征", "重新识别", "跑特征", "特征提取",
        "识别一下", "重跑特征", "再识别", "识别", "feature", "recognition"
    ],
    IntentType.PRICE_CALCULATION: [
        "重新计算", "重算", "算一下", "更新价格", "计价",
        "price", "calculate", "重进计算"
    ],
    IntentType.QUERY_DETAILS: [
        "怎么算", "计算详情", "详细步骤", "成本构成", "价格明细",
        "怎么计算", "如何计算", "计算过程", "details", "breakdown",
        "对吗", "正确吗", "是否正确", "这样对吗", "有问题吗", "是不是", "对不对",
        "为什么", "详情", "明细",
        "是什么", "什么", "多少", "哪个", "哪些", "几个",  # 🆕 查询类关键词
        "？", "吗"  # 🆕 疑问标记
    ],
    IntentType.DATA_MODIFICATION: [
        "改为", "修改", "设置为", "改成", "更改", "变更",
        "修改为", "改一下", "换成", "modify", "change", "update",
        "调整", "变成", "用"  # 🆕 添加"用"关键词，支持 "DIE-01用中丝" 格式
    ],
    IntentType.WEIGHT_PRICE_CALCULATION: [
        "按重量计算", "重量计算", "模架按重量", "按重量算价格",
        "重量价格", "按重量", "weight price", "weight calculation"
    ],
    IntentType.WEIGHT_PRICE_QUERY: [
        "按重量怎么算", "重量计算详情", "重量价格怎么来的",
        "为什么按重量", "按重量的计算", "重量怎么算",
        "weight price details", "weight calculation details"
    ],
}
