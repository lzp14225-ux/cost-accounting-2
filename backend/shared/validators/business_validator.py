"""
业务规则验证器
负责人：人员B2

职责：
1. 验证业务规则
2. 验证数据一致性
3. 验证外键关系
"""
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class BusinessValidator:
    """业务规则验证器"""
    
    @staticmethod
    def validate_subgraph_data(subgraph: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证子图数据的业务规则
        
        Args:
            subgraph: 子图数据
        
        Returns:
            (是否有效, 错误信息)
        """
        # 验证必需字段 (注意: material 字段在数据库中不存在,已从必需字段中移除)
        required_fields = ['subgraph_id']
        for field in required_fields:
            if field not in subgraph or subgraph[field] is None:
                return False, f"子图缺少必需字段: {field}"
        
        # 验证子图ID格式
        subgraph_id = subgraph['subgraph_id']
        if not isinstance(subgraph_id, str) or len(subgraph_id) == 0:
            return False, f"无效的子图ID: {subgraph_id}"
        
        # 验证重量的合理性 (如果存在)
        weight = subgraph.get('weight_kg')  # 注意字段名是 weight_kg
        if weight is not None:
            try:
                weight_float = float(weight)
                if weight_float <= 0:
                    return False, f"重量必须大于0，当前: {weight_float}kg"
                if weight_float > 50000:
                    return False, f"重量不能超过50000kg，当前: {weight_float}kg"
            except (TypeError, ValueError):
                return False, f"重量必须是数字，当前值: {weight}"
        
        return True, None
    
    @staticmethod
    def validate_feature_data(feature: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证特征数据的业务规则
        
        Args:
            feature: 特征数据
        
        Returns:
            (是否有效, 错误信息)
        """
        # 验证必需字段
        required_fields = ['feature_id', 'feature_type']
        for field in required_fields:
            if field not in feature or feature[field] is None:
                return False, f"特征缺少必需字段: {field}"
        
        return True, None
    
    @staticmethod
    def validate_price_snapshot(snapshot: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证价格快照的业务规则
        
        Args:
            snapshot: 价格快照数据
        
        Returns:
            (是否有效, 错误信息)
        """
        # 验证必需字段
        required_fields = ['snapshot_id', 'total_price']
        for field in required_fields:
            if field not in snapshot or snapshot[field] is None:
                return False, f"价格快照缺少必需字段: {field}"
        
        # 验证价格合理性
        total_price = snapshot.get('total_price', 0)
        if total_price < 0:
            return False, f"总价不能为负数: {total_price}"
        
        return True, None
    
    @staticmethod
    def validate_process_snapshot(snapshot: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证工艺快照的业务规则
        
        Args:
            snapshot: 工艺快照数据
        
        Returns:
            (是否有效, 错误信息)
        """
        # 验证必需字段
        required_fields = ['snapshot_id', 'process_type']
        for field in required_fields:
            if field not in snapshot or snapshot[field] is None:
                return False, f"工艺快照缺少必需字段: {field}"
        
        return True, None
    
    @staticmethod
    def validate_data_consistency(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证数据一致性
        
        Args:
            data: 完整数据（包含4个表）
        
        Returns:
            (是否有效, 错误信息)
        """
        # 验证子图数据
        subgraphs = data.get('subgraphs', [])
        for subgraph in subgraphs:
            is_valid, error = BusinessValidator.validate_subgraph_data(subgraph)
            if not is_valid:
                return False, f"子图验证失败: {error}"
        
        # 验证特征数据
        features = data.get('features', [])
        for feature in features:
            is_valid, error = BusinessValidator.validate_feature_data(feature)
            if not is_valid:
                return False, f"特征验证失败: {error}"
        
        # 验证价格快照
        price_snapshots = data.get('price_snapshots', [])
        for snapshot in price_snapshots:
            is_valid, error = BusinessValidator.validate_price_snapshot(snapshot)
            if not is_valid:
                return False, f"价格快照验证失败: {error}"
        
        # 验证工艺快照
        process_snapshots = data.get('process_snapshots', [])
        for snapshot in process_snapshots:
            is_valid, error = BusinessValidator.validate_process_snapshot(snapshot)
            if not is_valid:
                return False, f"工艺快照验证失败: {error}"
        
        return True, None
    
    @staticmethod
    def validate_foreign_keys(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证外键关系
        
        Args:
            data: 完整数据
        
        Returns:
            (是否有效, 错误信息)
        """
        # 收集所有子图ID
        subgraph_ids = {sg['subgraph_id'] for sg in data.get('subgraphs', [])}
        
        # 验证特征的子图ID引用
        features = data.get('features', [])
        for feature in features:
            subgraph_id = feature.get('subgraph_id')
            if subgraph_id and subgraph_id not in subgraph_ids:
                return False, f"特征 {feature.get('feature_id')} 引用了不存在的子图: {subgraph_id}"
        
        return True, None
