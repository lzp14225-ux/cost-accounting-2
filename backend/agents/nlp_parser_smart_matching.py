# Smart Matching Integration Methods for NLPParser
# These methods will be added to the NLPParser class

async def _try_smart_matching(
    self,
    text: str,
    context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    尝试使用智能匹配解析用户输入
    
    当常规解析失败时调用此方法，使用智能匹配器尝试找到用户想要修改的目标
    
    Args:
        text: 用户输入
        context: 数据上下文
    
    Returns:
        解析后的修改列表
    
    Raises:
        NeedsConfirmationException: 当找到多个候选时
    """
    from shared.input_normalizer import InputNormalizer
    from shared.smart_matcher import SmartMatcher
    from shared.match_evaluator import MatchEvaluator
    
    logger.info("🔍 使用智能匹配解析用户输入...")
    
    # 1. 标准化输入
    normalizer = InputNormalizer()
    
    # 尝试提取子图ID、材质、尺寸
    normalized_input = {}
    
    # 提取可能的子图ID
    import re
    subgraph_pattern = r'[A-Z]{2,4}[-_]?\d{1,2}'
    subgraph_match = re.search(subgraph_pattern, text, re.IGNORECASE)
    if subgraph_match:
        subgraph_id = subgraph_match.group()
        normalized_input['subgraph_ids'] = normalizer.normalize_subgraph_id(subgraph_id)
    
    # 提取可能的材质
    material_pattern = r'(CR12|SKD11|45#|718|P20|DC53|T00L0X\d+|TOOLOX\d+)'
    material_match = re.search(material_pattern, text, re.IGNORECASE)
    if material_match:
        material = material_match.group()
        normalized_input['material'] = normalizer.normalize_material(material)
    
    # 提取可能的尺寸
    dimension_pattern = r'(\d+(?:\.\d+)?)\s*[*×xX]\s*(\d+(?:\.\d+)?)\s*[*×xX]\s*(\d+(?:\.\d+)?)'
    dimension_match = re.search(dimension_pattern, text)
    if dimension_match:
        dimension_str = dimension_match.group()
        normalized_input['dimension'] = normalizer.normalize_dimension(dimension_str)
    
    if not normalized_input:
        logger.warning("⚠️  无法从输入中提取有效信息")
        return []
    
    # 2. 智能匹配
    raw_data = context.get("raw_data") or context
    subgraphs = raw_data.get("subgraphs", [])
    features = raw_data.get("features", [])
    
    # 构建匹配数据
    parts = []
    for sg in subgraphs:
        sg_id = sg.get("subgraph_id")
        # 查找对应的 feature
        feature = next((f for f in features if f.get("subgraph_id") == sg_id), None)
        if feature:
            parts.append({
                "subgraph_id": sg_id,
                "part_name": sg.get("part_name"),
                "part_code": sg.get("part_code"),
                "material": feature.get("material"),
                "length_mm": feature.get("length_mm"),
                "width_mm": feature.get("width_mm"),
                "thickness_mm": feature.get("thickness_mm")
            })
    
    matcher = SmartMatcher()
    matches = matcher.find_matches(normalized_input, parts)
    
    # 3. 评估匹配结果
    evaluator = MatchEvaluator()
    evaluation = evaluator.evaluate(matches)
    
    logger.info(f"📊 匹配评估: status={evaluation.status}, confidence={evaluation.confidence}, count={len(matches)}")
    
    # 4. 根据评估结果决定行动
    if evaluation.needs_confirmation:
        # 需要用户确认
        from agents.nlp_parser import NeedsConfirmationException
        
        # 格式化候选列表
        candidates = []
        for match in matches:
            candidates.append({
                "subgraph_id": match["subgraph_id"],
                "part_name": match.get("part_name", ""),
                "part_code": match.get("part_code", ""),
                "material": match.get("material", ""),
                "dimensions": f"{match.get('length_mm', 0)}×{match.get('width_mm', 0)}×{match.get('thickness_mm', 0)}"
            })
        
        raise NeedsConfirmationException(
            message=f"找到 {len(candidates)} 个可能的目标，请选择：",
            candidates=candidates,
            original_input=text,
            match_info={
                "normalized_input": normalized_input,
                "confidence": evaluation.confidence
            }
        )
    
    elif evaluation.status == "unique":
        # 唯一匹配，提取字段和值
        matched_part = matches[0]
        
        # 从用户输入中提取字段和值
        field, value = self._extract_field_and_value(text)
        
        if not field or not value:
            logger.warning("⚠️  无法提取字段和值")
            return []
        
        # 构建修改指令
        return [{
            "table": self._infer_table_from_field(field),
            "id": matched_part["subgraph_id"],
            "field": field,
            "value": value,
            "original_text": text
        }]
    
    else:
        # 没有匹配
        logger.warning("⚠️  智能匹配未找到目标")
        return []


async def _enhance_with_smart_matching(
    self,
    changes: List[Dict[str, Any]],
    context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    使用智能匹配增强解析结果
    
    检查解析结果中的ID是否明确，如果不明确则使用智能匹配
    
    Args:
        changes: 初步解析的修改列表
        context: 数据上下文
    
    Returns:
        增强后的修改列表
    
    Raises:
        NeedsConfirmationException: 当找到多个候选时
    """
    from shared.input_normalizer import InputNormalizer
    from shared.smart_matcher import SmartMatcher
    from shared.match_evaluator import MatchEvaluator
    
    enhanced_changes = []
    
    for change in changes:
        record_id = change.get("id")
        
        # 检查ID是否需要智能匹配
        # 1. ID为空
        # 2. ID看起来不像标准格式（没有连字符或下划线）
        # 3. ID是小写的（可能需要标准化）
        needs_matching = (
            not record_id or
            (isinstance(record_id, str) and 
             not re.search(r'[-_]', record_id) and 
             record_id.islower())
        )
        
        if not needs_matching:
            enhanced_changes.append(change)
            continue
        
        logger.info(f"🔍 ID '{record_id}' 需要智能匹配")
        
        # 使用智能匹配查找
        normalizer = InputNormalizer()
        normalized_input = {}
        
        if record_id:
            normalized_input['subgraph_ids'] = normalizer.normalize_subgraph_id(record_id)
        
        # 构建匹配数据
        raw_data = context.get("raw_data") or context
        subgraphs = raw_data.get("subgraphs", [])
        features = raw_data.get("features", [])
        
        parts = []
        for sg in subgraphs:
            sg_id = sg.get("subgraph_id")
            feature = next((f for f in features if f.get("subgraph_id") == sg_id), None)
            if feature:
                parts.append({
                    "subgraph_id": sg_id,
                    "part_name": sg.get("part_name"),
                    "part_code": sg.get("part_code"),
                    "material": feature.get("material"),
                    "length_mm": feature.get("length_mm"),
                    "width_mm": feature.get("width_mm"),
                    "thickness_mm": feature.get("thickness_mm")
                })
        
        matcher = SmartMatcher()
        matches = matcher.find_matches(normalized_input, parts)
        
        evaluator = MatchEvaluator()
        evaluation = evaluator.evaluate(matches)
        
        if evaluation.needs_confirmation:
            # 需要用户确认
            from agents.nlp_parser import NeedsConfirmationException
            
            candidates = []
            for match in matches:
                candidates.append({
                    "subgraph_id": match["subgraph_id"],
                    "part_name": match.get("part_name", ""),
                    "part_code": match.get("part_code", ""),
                    "material": match.get("material", ""),
                    "dimensions": f"{match.get('length_mm', 0)}×{match.get('width_mm', 0)}×{match.get('thickness_mm', 0)}"
                })
            
            raise NeedsConfirmationException(
                message=f"找到 {len(candidates)} 个可能的目标，请选择：",
                candidates=candidates,
                original_input=change.get("original_text", ""),
                match_info={
                    "original_id": record_id,
                    "confidence": evaluation.confidence
                }
            )
        
        elif evaluation.status == "unique":
            # 更新ID
            change["id"] = matches[0]["subgraph_id"]
            enhanced_changes.append(change)
            logger.info(f"✅ 智能匹配成功: {record_id} → {matches[0]['subgraph_id']}")
        
        else:
            # 没有匹配，保持原样
            enhanced_changes.append(change)
            logger.warning(f"⚠️  智能匹配未找到 {record_id}")
    
    return enhanced_changes


def _extract_field_and_value(self, text: str) -> tuple:
    """
    从文本中提取字段名和值
    
    Args:
        text: 用户输入
    
    Returns:
        (field, value) 元组
    """
    # 字段模式
    field_patterns = {
        r'材质|材料|material': 'material',
        r'长度|length': 'length_mm',
        r'宽度|width': 'width_mm',
        r'厚度|thickness': 'thickness_mm',
        r'数量|quantity': 'quantity',
        r'工艺|process': 'wire_process'
    }
    
    field = None
    for pattern, field_name in field_patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            field = field_name
            break
    
    if not field:
        return (None, None)
    
    # 值模式
    value_patterns = [
        r'(?:改为|改成|修改为|设置为|变为|换成)\s*([^\s，。、]+)',
        r'(?:为|是)\s*([^\s，。、]+)',
        r'=\s*([^\s，。、]+)'
    ]
    
    value = None
    for pattern in value_patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            break
    
    return (field, value)


def _infer_table_from_field(self, field: str) -> str:
    """
    根据字段名推断表名
    
    Args:
        field: 字段名
    
    Returns:
        表名
    """
    field_to_table = {
        "material": "features",
        "length_mm": "features",
        "width_mm": "features",
        "thickness_mm": "features",
        "quantity": "features",
        "wire_process": "subgraphs",
        "wire_process_note": "subgraphs",
        "part_name": "subgraphs",
        "part_code": "subgraphs"
    }
    
    return field_to_table.get(field, "subgraphs")
