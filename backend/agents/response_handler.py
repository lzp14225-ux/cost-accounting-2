"""
Response Handler - 响应处理器
负责人：人员B2

职责：
处理用户对澄清的响应（确认/拒绝/修改）
"""
import logging
from typing import Dict, Any, Optional

from .clarification_models import ResponseResult

logger = logging.getLogger(__name__)


class ResponseHandler:
    """响应处理器"""
    
    async def handle_confirm(
        self,
        clarification_id: str,
        parsed_entities: Dict[str, Any]
    ) -> ResponseResult:
        """
        处理确认响应
        
        将解析的实体转换为标准化输入
        
        Args:
            clarification_id: 澄清ID
            parsed_entities: 解析的实体
        
        Returns:
            ResponseResult: 包含标准化输入的结果
        """
        logger.info(f"✅ 处理确认响应: clarification_id={clarification_id}")
        
        try:
            # 生成标准化输入
            normalized_input = self._generate_normalized_input(parsed_entities)
            
            logger.info(f"✅ 标准化输入生成: {normalized_input}")
            
            return ResponseResult(
                success=True,
                normalized_input=normalized_input,
                requires_new_clarification=False
            )
        
        except Exception as e:
            logger.error(f"❌ 处理确认失败: {e}", exc_info=True)
            return ResponseResult(
                success=False,
                error_message=f"处理确认失败: {str(e)}",
                requires_new_clarification=False
            )
    
    async def handle_reject(
        self,
        clarification_id: str
    ) -> ResponseResult:
        """
        处理拒绝响应
        
        Args:
            clarification_id: 澄清ID
        
        Returns:
            ResponseResult: 包含错误信息的结果
        """
        logger.info(f"❌ 处理拒绝响应: clarification_id={clarification_id}")
        
        return ResponseResult(
            success=False,
            error_message="用户拒绝了系统的理解，请重新输入更清晰的指令",
            requires_new_clarification=False
        )
    
    async def handle_modify(
        self,
        clarification_id: str,
        modifications: Dict[str, Any]
    ) -> ResponseResult:
        """
        处理修改响应
        
        用户修改了系统解析的某些部分
        
        Args:
            clarification_id: 澄清ID
            modifications: 用户的修改内容
        
        Returns:
            ResponseResult: 可能需要新的澄清
        """
        logger.info(f"🔧 处理修改响应: clarification_id={clarification_id}")
        logger.debug(f"修改内容: {modifications}")
        
        try:
            # 应用修改
            modified_entities = self._apply_modifications(modifications)
            
            # 生成标准化输入
            normalized_input = self._generate_normalized_input(modified_entities)
            
            logger.info(f"✅ 修改后的标准化输入: {normalized_input}")
            
            return ResponseResult(
                success=True,
                normalized_input=normalized_input,
                requires_new_clarification=False
            )
        
        except Exception as e:
            logger.error(f"❌ 处理修改失败: {e}", exc_info=True)
            return ResponseResult(
                success=False,
                error_message=f"处理修改失败: {str(e)}",
                requires_new_clarification=True
            )
    
    def _generate_normalized_input(self, entities: Dict[str, Any]) -> str:
        """
        生成标准化输入
        
        将实体转换为规范的自然语言指令
        
        Args:
            entities: 提取的实体
        
        Returns:
            标准化的输入文本
        """
        part_code = entities.get("part_code", "")
        field = entities.get("field", "")
        value = entities.get("value", "")
        
        # 🆕 如果有最佳匹配值，使用它
        if "_best_match" in entities:
            value = entities["_best_match"]
        
        # 🆕 保持简洁的格式，让 NLPParser 自己处理
        # 格式：[零件代码][动作][值]
        # 例如："Die-01用中丝割一修一" 或 "DIE-01改成中丝割一修一"
        
        # 根据字段类型选择合适的动词
        if field == "process_code":
            # 工艺代码：使用"用"或"改成"
            normalized = f"{part_code}用{value}"
        elif field == "material":
            # 材质：使用"改成"
            normalized = f"{part_code}材质改成{value}"
        elif field in ["length_mm", "width_mm", "thickness_mm"]:
            # 尺寸：使用"改成"
            field_mapping = {
                "length_mm": "长度",
                "width_mm": "宽度",
                "thickness_mm": "厚度"
            }
            field_cn = field_mapping.get(field, field)
            normalized = f"{part_code}的{field_cn}改成{value}"
        elif field == "quantity":
            # 数量：使用"改成"
            normalized = f"{part_code}数量改成{value}"
        elif field == "weight":
            # 重量：使用"改成"
            normalized = f"{part_code}重量改成{value}"
        else:
            # 其他字段：使用通用格式
            normalized = f"{part_code}的{field}改成{value}"
        
        logger.info(f"✅ 生成标准化输入: {normalized}")
        
        return normalized
    
    def _apply_modifications(self, modifications: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用用户的修改
        
        Args:
            modifications: 用户的修改内容
                {
                    "original_entities": {...},
                    "changes": {
                        "part_code": "新值",
                        "value": "新值"
                    }
                }
        
        Returns:
            修改后的实体
        """
        original_entities = modifications.get("original_entities", {})
        changes = modifications.get("changes", {})
        
        # 应用修改
        modified_entities = original_entities.copy()
        modified_entities.update(changes)
        
        return modified_entities
