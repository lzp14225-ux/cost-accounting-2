"""
字段验证器
负责人：人员B2

职责：
1. 验证字段类型
2. 验证字段值范围
3. 验证字段格式
"""
import re
from typing import Any, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class FieldValidator:
    """字段验证器"""
    
    # 有效的材质代码
    VALID_MATERIALS = {
        'P20', '718', 'NAK80', 'S136', '2738', 
        'H13', 'SKD61', '2344', 'STAVAX',
        '420', '440C', 'DC53', 'SKH51',
        'CR12', 'CR12MOV', 'SKD11', 'SKH-51', 'SKH-9',
        'T00L0X33', 'T00L0X44', 'TOOLOX33', 'TOOLOX44', '45#'
    }
    
    # 字段长度限制
    MAX_STRING_LENGTH = 500
    MAX_TEXT_LENGTH = 5000
    
    @staticmethod
    def validate_material(value: str) -> tuple[bool, Optional[str]]:
        """
        验证材质代码
        
        Args:
            value: 材质代码
        
        Returns:
            (是否有效, 错误信息)
        """
        if not value:
            return False, "材质代码不能为空"
        
        if not isinstance(value, str):
            return False, "材质代码必须是字符串"
        
        # 转换为大写并去除空格
        value = value.upper().strip()
        
        if value not in FieldValidator.VALID_MATERIALS:
            return False, f"无效的材质代码: {value}，有效值: {', '.join(sorted(FieldValidator.VALID_MATERIALS))}"
        
        return True, None
    
    @staticmethod
    def validate_weight(value: Any) -> tuple[bool, Optional[str]]:
        """
        验证重量
        
        Args:
            value: 重量值（kg）
        
        Returns:
            (是否有效, 错误信息)
        """
        try:
            weight = float(value)
        except (TypeError, ValueError):
            return False, f"重量必须是数字，当前值: {value}"
        
        if weight <= 0:
            return False, f"重量必须大于0，当前值: {weight}"
        
        if weight > 50000:  # 50吨
            return False, f"重量不能超过50000kg，当前值: {weight}"
        
        return True, None
    
    @staticmethod
    def validate_price(value: Any) -> tuple[bool, Optional[str]]:
        """
        验证价格
        
        Args:
            value: 价格值（元）
        
        Returns:
            (是否有效, 错误信息)
        """
        try:
            price = float(value)
        except (TypeError, ValueError):
            return False, f"价格必须是数字，当前值: {value}"
        
        if price < 0:
            return False, f"价格不能为负数，当前值: {price}"
        
        if price > 10000000:  # 1000万
            return False, f"价格不能超过10000000元，当前值: {price}"
        
        return True, None
    
    @staticmethod
    def validate_quantity(value: Any) -> tuple[bool, Optional[str]]:
        """
        验证数量
        
        Args:
            value: 数量值
        
        Returns:
            (是否有效, 错误信息)
        """
        # 检查是否是浮点数（不允许）
        if isinstance(value, float) and not value.is_integer():
            return False, f"数量必须是整数，当前值: {value}"
        
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            return False, f"数量必须是整数，当前值: {value}"
        
        if quantity <= 0:
            return False, f"数量必须大于0，当前值: {quantity}"
        
        if quantity > 1000000:
            return False, f"数量不能超过1000000，当前值: {quantity}"
        
        return True, None
    
    @staticmethod
    def validate_string(value: Any, max_length: int = None) -> tuple[bool, Optional[str]]:
        """
        验证字符串
        
        Args:
            value: 字符串值
            max_length: 最大长度
        
        Returns:
            (是否有效, 错误信息)
        """
        if not isinstance(value, str):
            return False, f"必须是字符串，当前类型: {type(value).__name__}"
        
        max_len = max_length or FieldValidator.MAX_STRING_LENGTH
        
        if len(value) > max_len:
            return False, f"字符串长度不能超过{max_len}，当前长度: {len(value)}"
        
        return True, None
    
    @staticmethod
    def validate_text(value: Any) -> tuple[bool, Optional[str]]:
        """
        验证文本（长文本）
        
        Args:
            value: 文本值
        
        Returns:
            (是否有效, 错误信息)
        """
        return FieldValidator.validate_string(value, FieldValidator.MAX_TEXT_LENGTH)
    
    @staticmethod
    def validate_percentage(value: Any) -> tuple[bool, Optional[str]]:
        """
        验证百分比
        
        Args:
            value: 百分比值（0-100）
        
        Returns:
            (是否有效, 错误信息)
        """
        try:
            percentage = float(value)
        except (TypeError, ValueError):
            return False, f"百分比必须是数字，当前值: {value}"
        
        if percentage < 0 or percentage > 100:
            return False, f"百分比必须在0-100之间，当前值: {percentage}"
        
        return True, None
    
    @staticmethod
    def validate_dimension(value: Any) -> tuple[bool, Optional[str]]:
        """
        验证尺寸
        
        Args:
            value: 尺寸值（mm）
        
        Returns:
            (是否有效, 错误信息)
        """
        try:
            dimension = float(value)
        except (TypeError, ValueError):
            return False, f"尺寸必须是数字，当前值: {value}"
        
        if dimension <= 0:
            return False, f"尺寸必须大于0，当前值: {dimension}"
        
        if dimension > 10000:  # 10米
            return False, f"尺寸不能超过10000mm，当前值: {dimension}"
        
        return True, None
    
    @staticmethod
    def validate_field(field_name: str, value: Any, field_type: str = None) -> tuple[bool, Optional[str]]:
        """
        根据字段名自动验证
        
        Args:
            field_name: 字段名
            value: 字段值
            field_type: 字段类型（可选）
        
        Returns:
            (是否有效, 错误信息)
        """
        # 根据字段名推断验证方法
        field_lower = field_name.lower()
        
        if 'material' in field_lower or '材质' in field_lower:
            return FieldValidator.validate_material(value)
        
        elif 'weight' in field_lower or '重量' in field_lower:
            return FieldValidator.validate_weight(value)
        
        elif 'price' in field_lower or '价格' in field_lower or 'cost' in field_lower:
            return FieldValidator.validate_price(value)
        
        elif 'quantity' in field_lower or '数量' in field_lower:
            return FieldValidator.validate_quantity(value)
        
        elif 'percentage' in field_lower or '百分比' in field_lower or 'rate' in field_lower:
            return FieldValidator.validate_percentage(value)
        
        elif any(dim in field_lower for dim in ['length', 'width', 'height', 'thickness', '长度', '宽度', '高度', '厚度']):
            return FieldValidator.validate_dimension(value)
        
        elif 'description' in field_lower or 'note' in field_lower or '说明' in field_lower or '备注' in field_lower:
            return FieldValidator.validate_text(value)
        
        else:
            # 默认字符串验证
            return FieldValidator.validate_string(value)
