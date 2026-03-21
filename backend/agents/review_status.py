"""
审核状态枚举
负责人：人员B2

状态说明：
- REVIEWING: 审核中（可修改）
- COMPLETED: 已完成（只读，保留1小时）
- EXPIRED: 已过期
- CANCELLED: 已取消
"""
from enum import Enum


class ReviewStatus(str, Enum):
    """审核状态"""
    
    REVIEWING = "reviewing"      # 审核中（可修改）
    COMPLETED = "completed"      # 已完成（只读）
    EXPIRED = "expired"          # 已过期
    CANCELLED = "cancelled"      # 已取消
    
    def __str__(self):
        return self.value
