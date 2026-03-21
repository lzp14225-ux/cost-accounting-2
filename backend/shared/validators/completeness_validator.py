"""
数据完整性验证器
负责人：人员B2

职责：
1. 检查必填字段是否完整
2. 生成缺失字段报告
3. 生成 LLM 补全提示
"""
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class CompletenessValidator:
    """数据完整性验证器"""
    
    # 必填字段配置
    REQUIRED_FIELDS = {
        'features': {
            'length_mm': '长度(mm)',
            'width_mm': '宽度(mm)',
            'thickness_mm': '厚度(mm)',
            'quantity': '数量',
            'material': '材质'
        },
        # 可扩展其他表
        # 'subgraphs': {
        #     'weight_kg': '重量(kg)',
        #     'part_name': '零件名称'
        # },
    }
    
    @staticmethod
    def check_data_completeness(
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查数据完整性
        
        Args:
            data: 包含4个表的数据
        
        Returns:
            {
                "is_complete": bool,
                "missing_fields": [
                    {
                        "table": "features",
                        "record_id": "64",
                        "record_name": "PH2-04",
                        "missing": {
                            "material": "材质",
                            "length_mm": "长度(mm)"
                        }
                    }
                ],
                "summary": "发现 2 条记录缺少必填字段"
            }
        """
        missing_fields = []
        
        # 检查 features 表
        for feature in data.get('features', []):
            missing = CompletenessValidator._check_feature(feature)
            if missing:
                missing_fields.append({
                    "table": "features",
                    "record_id": str(feature.get('feature_id')),
                    "record_name": feature.get('subgraph_id', 'Unknown'),
                    "part_code": feature.get('part_code'),  # 🆕 添加零件编号
                    "part_name": feature.get('part_name'),  # 🆕 添加零件名称
                    "missing": missing,
                    "current_values": {
                        k: feature.get(k) for k in CompletenessValidator.REQUIRED_FIELDS['features'].keys()
                    }
                })
        
        # 可扩展检查其他表
        # for subgraph in data.get('subgraphs', []):
        #     missing = CompletenessValidator._check_subgraph(subgraph)
        #     if missing:
        #         missing_fields.append({...})
        
        is_complete = len(missing_fields) == 0
        
        return {
            "is_complete": is_complete,
            "missing_fields": missing_fields,
            "summary": f"发现 {len(missing_fields)} 条记录缺少必填字段" if not is_complete else "数据完整"
        }
    
    @staticmethod
    def _check_feature(feature: Dict[str, Any]) -> Dict[str, str]:
        """检查单个 feature 记录"""
        missing = {}
        
        for field, field_name in CompletenessValidator.REQUIRED_FIELDS['features'].items():
            value = feature.get(field)
            
            # 检查是否为空
            if value is None or value == '' or (isinstance(value, (int, float)) and value == 0):
                missing[field] = field_name
        
        return missing
    
    @staticmethod
    def generate_completion_prompt(
        missing_fields: List[Dict[str, Any]],
        context_data: Dict[str, Any]
    ) -> str:
        """
        生成 LLM 补全提示
        
        Args:
            missing_fields: 缺失字段列表
            context_data: 上下文数据(用于推理)
        
        Returns:
            给 LLM 的提示文本
        """
        prompt_parts = [
            "以下零件记录缺少必填字段,请根据已知信息推理并给出补全建议:\n"
        ]
        
        for idx, item in enumerate(missing_fields, 1):
            prompt_parts.append(f"\n【记录 {idx}】")
            prompt_parts.append(f"子图ID: {item['record_name']}")
            
            # 🆕 添加零件编号和零件名称
            if item.get('part_code'):
                prompt_parts.append(f"零件编号: {item['part_code']}")
            if item.get('part_name'):
                prompt_parts.append(f"零件名称: {item['part_name']}")
            
            prompt_parts.append(f"记录ID: {item['record_id']}")
            prompt_parts.append(f"缺失字段: {', '.join(item['missing'].values())}")
            
            # 添加上下文信息
            feature = CompletenessValidator._find_feature(
                context_data, 
                item['record_id']
            )
            if feature:
                prompt_parts.append(f"已知信息:")
                
                # 当前值
                current = item.get('current_values', {})
                if current.get('length_mm'):
                    prompt_parts.append(f"  - 长度: {current['length_mm']}mm")
                if current.get('width_mm'):
                    prompt_parts.append(f"  - 宽度: {current['width_mm']}mm")
                if current.get('thickness_mm'):
                    prompt_parts.append(f"  - 厚度: {current['thickness_mm']}mm")
                if current.get('quantity'):
                    prompt_parts.append(f"  - 数量: {current['quantity']}")
                if current.get('material'):
                    prompt_parts.append(f"  - 材质: {current['material']}")
                
                # 加工说明
                if feature.get('processing_instructions'):
                    instructions = feature['processing_instructions']
                    if isinstance(instructions, dict):
                        # 将所有值转换为字符串，处理可能的 list 类型
                        instruction_strs = []
                        for v in instructions.values():
                            if isinstance(v, list):
                                instruction_strs.append(', '.join(str(x) for x in v))
                            else:
                                instruction_strs.append(str(v))
                        prompt_parts.append(f"  - 加工说明: {', '.join(instruction_strs)[:100]}")
                
                # 热处理
                if feature.get('heat_treatment'):
                    prompt_parts.append(f"  - 热处理: {feature['heat_treatment']}")
        
        prompt_parts.append("\n请以自然语言形式给出补全建议,格式如下:")
        prompt_parts.append("'零件 PH2-04 的长度设为 309.5mm, 宽度设为 87mm, 厚度设为 47mm, 数量设为 1, 材质设为 Cr12mov'")
        prompt_parts.append("\n注意:")
        prompt_parts.append("1. 根据零件编号和加工说明推理合理的尺寸")
        prompt_parts.append("2. 材质通常从热处理信息中推断")
        prompt_parts.append("3. 数量默认为 1")
        
        return "\n".join(prompt_parts)
    
    @staticmethod
    def _find_feature(data: Dict[str, Any], feature_id: str) -> Optional[Dict[str, Any]]:
        """查找指定的 feature 记录"""
        for feature in data.get('features', []):
            if str(feature.get('feature_id')) == feature_id:
                return feature
        return None
