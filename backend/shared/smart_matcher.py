"""
SmartMatcher - 智能匹配器

职责：
1. 使用多种策略匹配零件
2. 支持精确匹配、模糊匹配、扩展字段匹配
3. 支持组合条件匹配
"""
import logging
from typing import List, Dict, Any, Optional
from .input_normalizer import InputNormalizer

logger = logging.getLogger(__name__)


class SmartMatcher:
    """智能匹配器"""
    
    def __init__(self, display_view: List[Dict]):
        """
        初始化智能匹配器
        
        Args:
            display_view: 展示视图数据（来自 DataViewBuilder）
        """
        self.display_view = display_view
        logger.info(f"✅ SmartMatcher 初始化完成，共 {len(display_view)} 条记录")
    
    def match_by_subgraph_id(
        self,
        input_id: str,
        fuzzy: bool = True
    ) -> List[Dict]:
        """
        通过子图ID匹配
        
        Args:
            input_id: 用户输入的ID
            fuzzy: 是否启用模糊匹配（默认 True）
        
        Returns:
            匹配的零件列表
        """
        matches = []
        
        if fuzzy:
            # 模糊匹配：标准化后比较
            input_variants = InputNormalizer.normalize_subgraph_id(input_id)
            logger.info(f"🔍 模糊匹配 '{input_id}'，变体: {input_variants}")
            
            # 🆕 调试：显示前几个 display_view 项的结构
            if self.display_view:
                sample = self.display_view[0]
                logger.debug(f"📋 display_view 示例结构: keys={list(sample.keys())}")
                logger.debug(f"📋 part_code: {sample.get('part_code')}")
                if "_source" in sample:
                    logger.debug(f"📋 _source.subgraph_id: {sample['_source'].get('subgraph_id')}")
            
            for item in self.display_view:
                # 🔑 修复：应该匹配 part_code，而不是 _source.subgraph_id
                # part_code 格式：B2-05, DIE-07 等
                # subgraph_id 格式：{uuid}_{part_code}
                part_code = item.get("part_code", "")
                
                if not part_code:
                    continue
                
                # 标准化 part_code
                db_variants = InputNormalizer.normalize_subgraph_id(part_code)
                
                # 检查是否有交集
                if set(input_variants) & set(db_variants):
                    matches.append(item)
                    logger.info(f"✅ 匹配: {part_code} (变体: {db_variants})")
                else:
                    # 🆕 调试：显示未匹配的原因
                    logger.debug(f"⏭️  跳过: {part_code} (变体: {db_variants}, 无交集)")
        else:
            # 精确匹配
            logger.debug(f"🔍 精确匹配 '{input_id}'")
            
            for item in self.display_view:
                # 🔑 修复：应该匹配 part_code
                if item.get("part_code") == input_id:
                    matches.append(item)
                    logger.debug(f"✅ 精确匹配: {input_id}")
        
        logger.info(f"📊 匹配结果: {len(matches)} 个零件")
        return matches
    
    def match_by_part_name(
        self,
        part_name: str,
        exact: bool = False
    ) -> List[Dict]:
        """
        通过零件名称匹配
        
        Args:
            part_name: 零件名称
            exact: 是否精确匹配（默认 False，支持包含匹配）
        
        Returns:
            匹配的零件列表
        """
        matches = []
        part_name_lower = part_name.lower().strip()
        
        logger.debug(f"🔍 通过零件名称匹配 '{part_name}' (exact={exact})")
        
        for item in self.display_view:
            item_name = item.get("part_name", "")
            if not item_name:
                continue
            
            item_name_lower = item_name.lower().strip()
            
            if exact:
                # 精确匹配
                if item_name_lower == part_name_lower:
                    matches.append(item)
            else:
                # 包含匹配
                if part_name_lower in item_name_lower:
                    matches.append(item)
        
        logger.info(f"📊 匹配结果: {len(matches)} 个零件")
        return matches
    
    def match_by_part_code(
        self,
        part_code: str,
        fuzzy: bool = True
    ) -> List[Dict]:
        """
        通过零件编码匹配
        
        Args:
            part_code: 零件编码
            fuzzy: 是否启用模糊匹配
        
        Returns:
            匹配的零件列表
        """
        matches = []
        
        if fuzzy:
            # 模糊匹配：支持前缀匹配
            code_upper = part_code.upper().strip()
            logger.debug(f"🔍 通过零件编码模糊匹配 '{part_code}'")
            
            for item in self.display_view:
                item_code = item.get("part_code", "")
                if not item_code:
                    continue
                
                item_code_upper = item_code.upper().strip()
                
                # 支持前缀匹配或完全匹配
                if item_code_upper.startswith(code_upper) or item_code_upper == code_upper:
                    matches.append(item)
        else:
            # 精确匹配
            logger.debug(f"🔍 通过零件编码精确匹配 '{part_code}'")
            
            for item in self.display_view:
                if item.get("part_code") == part_code:
                    matches.append(item)
        
        logger.info(f"📊 匹配结果: {len(matches)} 个零件")
        return matches
    
    def match_by_material(self, material: str) -> List[Dict]:
        """
        通过材质匹配
        
        Args:
            material: 材质代码
        
        Returns:
            匹配的零件列表
        """
        matches = []
        
        # 标准化输入材质
        normalized_material = InputNormalizer.normalize_material(material)
        logger.debug(f"🔍 通过材质匹配 '{material}' (标准化: '{normalized_material}')")
        
        for item in self.display_view:
            item_material = item.get("material", "")
            if not item_material:
                continue
            
            # 标准化数据库中的材质
            normalized_item_material = InputNormalizer.normalize_material(item_material)
            
            if normalized_item_material == normalized_material:
                matches.append(item)
        
        logger.info(f"📊 匹配结果: {len(matches)} 个零件")
        return matches
    
    def match_by_dimension(
        self,
        length: float,
        width: float,
        thickness: float,
        tolerance: float = 0.1
    ) -> List[Dict]:
        """
        通过尺寸匹配（带容差）
        
        Args:
            length: 长度
            width: 宽度
            thickness: 厚度
            tolerance: 容差（默认 0.1mm）
        
        Returns:
            匹配的零件列表
        """
        matches = []
        
        logger.debug(f"🔍 通过尺寸匹配 {length}*{width}*{thickness} (容差: ±{tolerance}mm)")
        
        for item in self.display_view:
            item_length = item.get("length_mm")
            item_width = item.get("width_mm")
            item_thickness = item.get("thickness_mm")
            
            # 检查是否所有尺寸字段都存在
            if not all([item_length is not None, item_width is not None, item_thickness is not None]):
                continue
            
            try:
                # 转换为浮点数
                item_length = float(item_length)
                item_width = float(item_width)
                item_thickness = float(item_thickness)
                
                # 检查是否在容差范围内
                if (abs(item_length - length) <= tolerance and
                    abs(item_width - width) <= tolerance and
                    abs(item_thickness - thickness) <= tolerance):
                    matches.append(item)
                    logger.debug(f"✅ 匹配: {item_length}*{item_width}*{item_thickness}")
            except (ValueError, TypeError) as e:
                logger.debug(f"⏭️  跳过无效尺寸: {e}")
                continue
        
        logger.info(f"📊 匹配结果: {len(matches)} 个零件")
        return matches
    
    def match_by_dimension_string(
        self,
        dimension_str: str,
        tolerance: float = 0.1
    ) -> List[Dict]:
        """
        通过尺寸字符串匹配
        
        Args:
            dimension_str: 尺寸字符串（如 "200*150*30"）
            tolerance: 容差
        
        Returns:
            匹配的零件列表
        """
        # 解析尺寸字符串
        dimensions = InputNormalizer.normalize_dimension(dimension_str)
        
        if not dimensions:
            logger.warning(f"⚠️  无法解析尺寸字符串: '{dimension_str}'")
            return []
        
        return self.match_by_dimension(
            dimensions["length"],
            dimensions["width"],
            dimensions["thickness"],
            tolerance
        )
    
    def match_by_multiple_criteria(
        self,
        criteria: Dict[str, Any]
    ) -> List[Dict]:
        """
        通过多个条件匹配（取交集）
        
        Args:
            criteria: 匹配条件字典
                {
                    "subgraph_id": "PH204",
                    "material": "45#",
                    "dimension": "200*150*30"
                }
        
        Returns:
            匹配的零件列表
        """
        logger.debug(f"🔍 通过多个条件匹配: {criteria}")
        
        # 初始化为所有记录
        result = self.display_view.copy()
        
        # 逐个条件过滤
        if "subgraph_id" in criteria:
            matches = self.match_by_subgraph_id(criteria["subgraph_id"], fuzzy=True)
            result = [item for item in result if item in matches]
            logger.debug(f"📊 subgraph_id 过滤后: {len(result)} 个零件")
        
        if "part_name" in criteria:
            matches = self.match_by_part_name(criteria["part_name"], exact=False)
            result = [item for item in result if item in matches]
            logger.debug(f"📊 part_name 过滤后: {len(result)} 个零件")
        
        if "part_code" in criteria:
            matches = self.match_by_part_code(criteria["part_code"], fuzzy=True)
            result = [item for item in result if item in matches]
            logger.debug(f"📊 part_code 过滤后: {len(result)} 个零件")
        
        if "material" in criteria:
            matches = self.match_by_material(criteria["material"])
            result = [item for item in result if item in matches]
            logger.debug(f"📊 material 过滤后: {len(result)} 个零件")
        
        if "dimension" in criteria:
            matches = self.match_by_dimension_string(criteria["dimension"])
            result = [item for item in result if item in matches]
            logger.debug(f"📊 dimension 过滤后: {len(result)} 个零件")
        
        logger.info(f"📊 最终匹配结果: {len(result)} 个零件")
        return result
    
    def match(
        self,
        input_text: str,
        context: Dict[str, Any]
    ) -> List[Dict]:
        """
        智能匹配（自动选择策略）
        
        Args:
            input_text: 用户输入文本
            context: 上下文信息
        
        Returns:
            匹配的零件列表
        """
        logger.info(f"🔍 智能匹配: '{input_text}'")
        
        # 尝试作为子图ID匹配
        matches = self.match_by_subgraph_id(input_text, fuzzy=True)
        if matches:
            logger.info(f"✅ 通过子图ID匹配成功")
            return matches
        
        # 尝试作为零件名称匹配
        matches = self.match_by_part_name(input_text, exact=False)
        if matches:
            logger.info(f"✅ 通过零件名称匹配成功")
            return matches
        
        # 尝试作为零件编码匹配
        matches = self.match_by_part_code(input_text, fuzzy=True)
        if matches:
            logger.info(f"✅ 通过零件编码匹配成功")
            return matches
        
        logger.warning(f"⚠️  未找到匹配的零件")
        return []
