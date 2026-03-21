"""
Confirmation Generator - 确认消息生成器
负责人：人员B2

职责：
生成用户友好的确认消息，清晰展示系统的理解
"""
import logging
from typing import Dict, Any

from .clarification_models import (
    ConfirmationMessage,
    ValidationResult,
    create_default_response_options
)
from shared.process_code_mapping import PROCESS_DETAIL_MAPPING

logger = logging.getLogger(__name__)


class ConfirmationGenerator:
    """确认消息生成器"""
    
    # 字段名映射（代码 → 中文）
    FIELD_NAME_MAPPING = {
        "process_code": "工艺代码",
        "material": "材质",
        "length_mm": "长度",
        "width_mm": "宽度",
        "thickness_mm": "厚度",
        "quantity": "数量",
        "weight": "重量",
        "heat_treatment": "热处理",
        "process_unit_price": "工艺单价",
        "material_unit_price": "材料单价",
        "part_code": "零件代码",
        "part_name": "零件名称"
    }
    
    def generate(
        self,
        validation_result: ValidationResult,
        user_input: str
    ) -> ConfirmationMessage:
        """
        生成确认消息
        
        消息格式：
        ```
        您是要 [动作] [零件代码] 的 [字段名] 为 [值] 吗？
        
        我的理解：
        - 零件：DIE-01
        - 字段：工艺代码 (process_code)
        - 新值：中丝割一修一 (middle_and_one)
        
        [确认] [拒绝] [修改]
        ```
        
        Args:
            validation_result: 验证结果
            user_input: 原始用户输入
        
        Returns:
            ConfirmationMessage: 确认消息对象
        """
        logger.info(f"📝 生成确认消息...")
        
        entities = validation_result.extracted_entities
        
        # 1. 生成主消息文本
        message_text = self._generate_main_message(entities, user_input)
        
        # 2. 构建解析结果展示
        parsed_interpretation = self._build_interpretation(entities)
        
        # 3. 创建响应选项
        options = create_default_response_options()
        
        logger.info(f"✅ 确认消息生成完成")
        
        return ConfirmationMessage(
            message_text=message_text,
            parsed_interpretation=parsed_interpretation,
            options=options
        )
    
    def _generate_main_message(
        self,
        entities: Dict[str, Any],
        user_input: str
    ) -> str:
        """生成主消息文本"""
        part_code = entities.get("part_code")
        field = entities.get("field")
        value = entities.get("value", "")
        confidence = entities.get("confidence", 1.0)
        
        # 🆕 检查是否无法识别输入
        # 条件1: 所有关键字段都是 None
        # 条件2: 只有 part_code 但没有 field（信息不完整）
        # 条件3: 置信度很低（< 0.6）且缺少关键信息
        if (not part_code and not field) or \
           (part_code and not field and confidence < 0.6) or \
           (not part_code and field and confidence < 0.6):
            # 无法识别的输入，使用友好的错误提示
            return self._generate_unrecognized_input_message(user_input, entities)
        
        # 格式化字段名
        field_cn = self._format_field_name(field) if field else "未知字段"
        part_code_display = part_code if part_code else "未知零件"
        
        # 🆕 检查是否有模糊匹配的建议
        suggestions = entities.get("_suggestions", [])
        
        if suggestions and len(suggestions) > 1:
            # 有多个建议，显示选项
            message = f"检测到您想修改 {part_code_display} 的{field_cn}，请选择：\n\n"
            for i, suggestion in enumerate(suggestions[:5], 1):
                message += f"{i}. {suggestion}\n"
            message += f"\n原始输入：{user_input}"
        elif value:
            # 有明确的值（可能是模糊匹配的最佳值）
            value_display = self._format_value(field, value, include_code=False)
            message = f"您是要修改 {part_code_display} 的{field_cn}为【{value_display}】吗？\n\n"
            message += f"原始输入：{user_input}"
        else:
            # 没有值，询问
            message = f"您是要修改 {part_code_display} 的{field_cn}吗？请指定新的值。\n\n"
            message += f"原始输入：{user_input}"
        
        return message
    
    def _generate_unrecognized_input_message(
        self,
        user_input: str,
        entities: Dict[str, Any]
    ) -> str:
        """
        生成无法识别输入的友好提示
        
        当用户输入无法识别时（如随机字符、数字等），
        生成更友好的错误提示，而不是"您是要修改 None 的None吗？"
        
        Args:
            user_input: 用户原始输入
            entities: LLM 提取的实体（可能包含 reasoning）
        
        Returns:
            友好的错误提示消息
        """
        # 获取 LLM 的推理信息
        reasoning = entities.get("reasoning", "")
        confidence = entities.get("confidence", 0)
        
        # 根据置信度和推理生成不同的提示
        if confidence < 0.3:
            # 完全无法识别
            message = f"抱歉，我无法理解您的输入「{user_input}」。\n\n"
            message += "请使用以下格式：\n"
            message += "• 修改工艺：「DIE-01用慢丝」或「DIE-01工艺改为慢丝割一修三」\n"
            message += "• 修改材质：「PU-01材质改为718」\n"
            message += "• 修改尺寸：「BL-01长度改为100」\n"
            message += "• 查询详情：「查询DIE-01的工艺」或「DIE-01的价格是多少」\n\n"
            
            if reasoning:
                message += f"提示：{reasoning}"
        else:
            # 部分识别，但信息不完整
            message = f"您的输入「{user_input}」信息不够完整。\n\n"
            
            if reasoning:
                message += f"{reasoning}\n\n"
            
            message += "请提供完整的信息，例如：\n"
            message += "• 零件代码（如 DIE-01, PU-01）\n"
            message += "• 要修改的字段（如 工艺、材质、长度）\n"
            message += "• 新的值\n"
        
        return message
    
    def _build_interpretation(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """构建解析结果展示"""
        interpretation = {
            "original_input": entities.get("original_input", ""),
            "extracted_entities": []
        }
        
        # 零件代码
        if "part_code" in entities:
            interpretation["extracted_entities"].append({
                "type": "零件",
                "value": entities["part_code"],
                "field": "part_code"
            })
        
        # 字段名
        if "field" in entities:
            field = entities["field"]
            field_cn = self._format_field_name(field)
            interpretation["extracted_entities"].append({
                "type": "字段",
                "value": f"{field_cn} ({field})",
                "field": "field"
            })
        
        # 值
        if "value" in entities:
            field = entities.get("field", "")
            value = entities["value"]
            value_display = self._format_value(field, value, include_code=True)
            interpretation["extracted_entities"].append({
                "type": "新值",
                "value": value_display,
                "field": "value"
            })
        
        return interpretation
    
    def _format_field_name(self, field: str) -> str:
        """格式化字段名为用户友好的中文"""
        return self.FIELD_NAME_MAPPING.get(field, field)
    
    def _format_value(
        self,
        field: str,
        value: str,
        include_code: bool = True
    ) -> str:
        """
        格式化值为用户友好的显示
        
        例如：
        - process_code: "中丝割一修一 (middle_and_one)"
        - material: "CR12"
        
        Args:
            field: 字段名
            value: 值
            include_code: 是否包含代码（如 middle_and_one）
        
        Returns:
            格式化后的显示文本
        """
        # 如果是工艺代码，查找完整名称
        if field == "process_code":
            # 查找 ProcessCodeMapping
            if value in PROCESS_DETAIL_MAPPING:
                process_info = PROCESS_DETAIL_MAPPING[value]
                note = process_info["note"]
                sub_category = process_info["sub_category"]
                
                if include_code:
                    return f"{note} ({sub_category})"
                else:
                    return note
        
        # 其他字段直接返回
        return value
    
    def generate_multiple_candidates(
        self,
        candidates: list[Dict[str, Any]],
        user_input: str
    ) -> ConfirmationMessage:
        """
        生成多候选确认消息
        
        当有多个可能的解释时使用
        
        Args:
            candidates: 候选列表，每个包含 entities 和 confidence
            user_input: 原始用户输入
        
        Returns:
            ConfirmationMessage: 确认消息对象
        """
        logger.info(f"📝 生成多候选确认消息: {len(candidates)} 个候选")
        
        # 限制最多5个候选
        candidates = candidates[:5]
        
        # 按置信度排序
        candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        # 生成消息文本
        message_text = "检测到多个可能的解释，请选择：\n\n"
        
        for i, candidate in enumerate(candidates, 1):
            entities = candidate.get("entities", {})
            confidence = candidate.get("confidence", 0)
            
            part_code = entities.get("part_code", "未知")
            field = entities.get("field", "未知")
            value = entities.get("value", "未知")
            
            field_cn = self._format_field_name(field)
            value_display = self._format_value(field, value, include_code=False)
            
            message_text += f"{i}. 修改 {part_code} 的{field_cn}为 {value_display} (置信度: {confidence:.0%})\n"
        
        message_text += f"\n原始输入：{user_input}"
        
        # 构建解析结果
        parsed_interpretation = {
            "original_input": user_input,
            "candidates": [
                {
                    "index": i,
                    "entities": candidate.get("entities", {}),
                    "confidence": candidate.get("confidence", 0)
                }
                for i, candidate in enumerate(candidates, 1)
            ]
        }
        
        # 创建响应选项（包含选择和拒绝）
        from .clarification_models import ResponseOption, ResponseType
        options = [
            ResponseOption(
                type=ResponseType.CONFIRM,
                label="选择",
                action="select_candidate"
            ),
            ResponseOption(
                type=ResponseType.REJECT,
                label="都不是",
                action="reject_all_candidates"
            )
        ]
        
        return ConfirmationMessage(
            message_text=message_text,
            parsed_interpretation=parsed_interpretation,
            options=options
        )
    
    def generate_missing_field_question(
        self,
        missing_fields: list[str],
        user_input: str,
        examples: Dict[str, list[str]] = None
    ) -> ConfirmationMessage:
        """
        生成缺失字段询问消息
        
        Args:
            missing_fields: 缺失的字段列表
            user_input: 原始用户输入
            examples: 每个字段的示例值
        
        Returns:
            ConfirmationMessage: 确认消息对象
        """
        logger.info(f"📝 生成缺失字段询问: {missing_fields}")
        
        message_text = "您的输入缺少一些关键信息，请补充：\n\n"
        
        for field in missing_fields:
            field_cn = self._format_field_name(field)
            message_text += f"- {field_cn} ({field})"
            
            # 添加示例
            if examples and field in examples:
                field_examples = examples[field][:3]
                message_text += f"\n  示例: {', '.join(field_examples)}"
            
            message_text += "\n"
        
        message_text += f"\n原始输入：{user_input}"
        
        # 构建解析结果
        parsed_interpretation = {
            "original_input": user_input,
            "missing_fields": [
                {
                    "field": field,
                    "field_cn": self._format_field_name(field),
                    "examples": examples.get(field, []) if examples else []
                }
                for field in missing_fields
            ]
        }
        
        # 创建响应选项
        from .clarification_models import ResponseOption, ResponseType
        options = [
            ResponseOption(
                type=ResponseType.MODIFY,
                label="补充信息",
                action="provide_missing_fields"
            ),
            ResponseOption(
                type=ResponseType.REJECT,
                label="取消",
                action="cancel_operation"
            )
        ]
        
        return ConfirmationMessage(
            message_text=message_text,
            parsed_interpretation=parsed_interpretation,
            options=options
        )
