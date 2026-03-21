"""
修改验证器
负责人：人员B2

职责：
1. 验证修改的合法性
2. 验证修改的字段是否存在
3. 验证修改的值是否合法
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

from .field_validator import FieldValidator
from .business_validator import BusinessValidator

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    error_message: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class ModificationValidator:
    """修改验证器"""
    
    # 表名到ID字段的映射
    TABLE_ID_FIELDS = {
        'features': 'subgraph_id',  # features 表使用 subgraph_id 作为主键
        'job_price_snapshots': 'snapshot_id',  # 🆕 修正表名
        'subgraphs': 'subgraph_id'
    }
    
    # 允许修改的字段（白名单）
    ALLOWED_FIELDS = {
        'subgraphs': {
            'material', 'weight', 'length', 'width', 'height',
            'thickness', 'description', 'process_notes',
            # 🆕 添加工艺字段
            'wire_process', 'wire_process_note'
        },
        'features': {
            'feature_type', 'quantity', 'description', 'parameters',
            # 🆕 添加尺寸字段
            'material', 'length_mm', 'width_mm', 'thickness_mm',
            'heat_treatment', 'calculated_weight_kg',
            'top_view_wire_length', 'front_view_wire_length', 'side_view_wire_length',
            'boring_length_mm', 'processing_instructions'
        },
        'job_price_snapshots': {  # 🆕 修正表名
            'material_cost', 'processing_cost', 'total_price', 'notes',
            # 🆕 添加价格相关字段
            'price', 'unit', 'work_hours', 'min_num', 'add_price', 'weight_num'
        }
    }
    
    @staticmethod
    def validate_changes(
        changes: List[Dict[str, Any]],
        current_data: Dict[str, Any]
    ) -> ValidationResult:
        """
        验证修改列表
        
        Args:
            changes: 修改列表
            current_data: 当前数据
        
        Returns:
            ValidationResult: 验证结果
        """
        if not changes:
            return ValidationResult(
                is_valid=False,
                error_message="修改列表为空"
            )
        
        warnings = []
        
        for i, change in enumerate(changes):
            # 验证单个修改
            result = ModificationValidator.validate_single_change(change, current_data)
            
            if not result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"第 {i+1} 个修改验证失败: {result.error_message}"
                )
            
            # 收集警告
            warnings.extend(result.warnings)
        
        return ValidationResult(
            is_valid=True,
            warnings=warnings
        )
    
    @staticmethod
    def validate_single_change(
        change: Dict[str, Any],
        current_data: Dict[str, Any]
    ) -> ValidationResult:
        """
        验证单个修改
        
        Args:
            change: 修改信息
                {
                    "table": "subgraphs",
                    "id": "UP01",
                    "field": "material",
                    "value": "718"
                }
            current_data: 当前数据
        
        Returns:
            ValidationResult: 验证结果
        """
        warnings = []
        
        # 1. 验证必需字段
        required_base_fields = ['table', 'field', 'value']
        for field in required_base_fields:
            if field not in change:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"修改缺少必需字段: {field}"
                )
        
        # 🆕 必须有 id 或 filter 之一
        if 'id' not in change and 'filter' not in change:
            return ValidationResult(
                is_valid=False,
                error_message="修改缺少必需字段: id 或 filter（必须提供其中之一）"
            )
        
        table = change['table']
        record_id = change.get('id')  # 可能为 None
        filter_conditions = change.get('filter')  # 可能为 None
        field = change['field']
        value = change['value']
        
        # 2. 验证表名
        if table not in ModificationValidator.TABLE_ID_FIELDS:
            return ValidationResult(
                is_valid=False,
                error_message=f"无效的表名: {table}，有效值: {', '.join(ModificationValidator.TABLE_ID_FIELDS.keys())}"
            )
        
        # 3. 验证字段是否允许修改
        if table in ModificationValidator.ALLOWED_FIELDS:
            allowed_fields = ModificationValidator.ALLOWED_FIELDS[table]
            if field not in allowed_fields:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"表 {table} 不允许修改字段 {field}，允许修改的字段: {', '.join(allowed_fields)}"
                )
        
        # 4. 验证记录是否存在（如果使用 ID 匹配）
        if record_id:
            record_exists, record = ModificationValidator._find_record(
                current_data, table, record_id
            )
            
            if not record_exists:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"表 {table} 中不存在 ID 为 {record_id} 的记录"
                )
            
            # 5. 验证字段是否存在
            if field not in record:
                warnings.append(f"记录中不存在字段 {field}，将作为新字段添加")
        
        elif filter_conditions:
            # 🆕 使用 filter 匹配时，跳过记录存在性验证
            # 因为可能匹配多条记录，在应用修改时再验证
            warnings.append(f"使用过滤条件匹配，将在应用修改时验证记录存在性")
            record = None  # 无法预先获取记录
        
        else:
            return ValidationResult(
                is_valid=False,
                error_message="必须提供 id 或 filter"
            )
        
        # 6. 验证字段值
        is_valid, error = FieldValidator.validate_field(field, value)
        if not is_valid:
            return ValidationResult(
                is_valid=False,
                error_message=f"字段 {field} 的值验证失败: {error}"
            )
        
        # 7. 验证修改后的数据一致性（仅当有具体记录时）
        if record:
            modified_record = record.copy()
            modified_record[field] = value
        else:
            # 使用 filter 匹配时，无法预先验证，跳过
            modified_record = {field: value}
        
        # 根据表类型进行字段级别的验证
        if table == 'features':
            # 对于 features 表，验证尺寸字段的合理性
            if field in ['length_mm', 'width_mm', 'thickness_mm']:
                try:
                    value_float = float(value)
                    if value_float <= 0:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"{field} 必须大于 0，当前值: {value_float}"
                        )
                    if value_float > 10000:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"{field} 不能超过 10000mm，当前值: {value_float}"
                        )
                except (TypeError, ValueError):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"{field} 必须是数字，当前值: {value}"
                    )
            
            # 验证数量
            elif field == 'quantity':
                try:
                    quantity = int(value)
                    if quantity <= 0:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"数量必须大于 0，当前值: {quantity}"
                        )
                except (TypeError, ValueError):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"数量必须是整数，当前值: {value}"
                    )
        
        elif table == 'subgraphs':
            # 对于 subgraphs 表，验证重量
            if field == 'weight_kg':
                try:
                    weight = float(value)
                    if weight <= 0:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"重量必须大于 0，当前值: {weight}"
                        )
                    if weight > 50000:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"重量不能超过 50000kg，当前值: {weight}"
                        )
                except (TypeError, ValueError):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"重量必须是数字，当前值: {value}"
                    )
        
        elif table == 'job_price_snapshots':
            # 对于 job_price_snapshots 表，验证价格
            if field == 'price':
                try:
                    price = float(value)
                    if price < 0:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"价格不能为负数，当前值: {price}"
                        )
                except (TypeError, ValueError):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"价格必须是数字，当前值: {value}"
                    )
        
        # 注意：我们移除了完整记录的业务规则验证，因为：
        # 1. 原始记录可能本身就不完整（缺少某些必需字段）
        # 2. 我们只需要验证被修改的字段是否合理
        # 3. 完整性验证应该在数据提交到数据库时进行
        
        return ValidationResult(
            is_valid=True,
            warnings=warnings
        )
    
    @staticmethod
    def _find_record(
        data: Dict[str, Any],
        table: str,
        record_id: str
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        查找记录
        
        Args:
            data: 完整数据
            table: 表名
            record_id: 记录ID
        
        Returns:
            (是否找到, 记录数据)
        """
        if table not in data:
            return False, None
        
        records = data[table]
        if not isinstance(records, list):
            return False, None
        
        # 获取ID字段名
        id_field = ModificationValidator.TABLE_ID_FIELDS.get(table, 'id')
        
        # 查找记录（支持类型转换比较）
        for record in records:
            record_value = record.get(id_field)
            
            # 🆕 尝试类型转换比较（处理 int vs str 的情况）
            if record_value == record_id:
                return True, record
            
            # 如果直接比较失败，尝试转换为字符串比较
            if str(record_value) == str(record_id):
                return True, record
            
            # 如果是数字类型，尝试转换为数字比较
            try:
                if int(record_value) == int(record_id):
                    return True, record
            except (ValueError, TypeError):
                pass
        
        return False, None
    
    @staticmethod
    def validate_batch_changes(
        changes_list: List[List[Dict[str, Any]]],
        current_data: Dict[str, Any]
    ) -> ValidationResult:
        """
        验证批量修改
        
        Args:
            changes_list: 多个修改列表
            current_data: 当前数据
        
        Returns:
            ValidationResult: 验证结果
        """
        all_warnings = []
        
        for i, changes in enumerate(changes_list):
            result = ModificationValidator.validate_changes(changes, current_data)
            
            if not result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"第 {i+1} 批修改验证失败: {result.error_message}"
                )
            
            all_warnings.extend(result.warnings)
        
        return ValidationResult(
            is_valid=True,
            warnings=all_warnings
        )
