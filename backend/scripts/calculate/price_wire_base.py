"""
线割基础价格计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（part_name, wire_process, 尺寸, metadata）
2. 调用 wire_base_search 获取线割工艺和价格信息
3. 如果 has_auto_material=True 且 needs_heat_treatment=True，调用 price_tooth_hole 计算牙孔周长
4. 根据 wire_process 匹配工艺条件（conditions）
5. 解析 metadata 中的 wire_cut_details，计算每个加工说明的费用
6. 将牙孔周长加到对应视图的线长上
7. 应用 extra_thick 和 slider 规则
8. 更新 processing_cost_calculation_details 表
"""
from typing import List, Dict, Any, Tuple
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_wire_base_price",
    "description": "计算线割基础价格：根据零件信息和线割工艺计算加工费用，如果has_auto_material和needs_heat_treatment都为True，则加上牙孔周长",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode、wire_base 和可选的 tooth_hole"
            },
            "job_id": {
                "type": "string",
                "description": "任务ID (UUID)"
            },
            "subgraph_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "子图ID列表"
            }
        },
        "required": ["search_data"]
    },
    "handler": "calculate",
    "needs": ["base_itemcode", "wire_base"],
    "optional": ["tooth_hole"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算线割基础价格
    
    Args:
        search_data: 检索数据，包含 base_itemcode、wire_base 和可选的 tooth_hole
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    wire_data = search_data["wire_base"]
    tooth_hole_data = search_data.get("tooth_hole")  # 可选的牙孔数据
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating wire base price for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 3: 构建工艺映射 (conditions -> wire_part)
    wire_parts = wire_data.get("wire_parts", [])
    if not wire_parts:
        logger.warning(f"No wire_parts found in wire_data for job_id: {job_id}")
        return {
            "job_id": job_id,
            "results": [],
            "message": "未找到线割工艺数据"
        }
    
    wire_map = {wp["conditions"]: wp for wp in wire_parts}
    
    # Step 4: 构建规则映射
    rule_map = _build_rule_map(wire_data.get("rule_prices", []))
    
    # Step 5: 如果有 tooth_hole 数据，构建牙孔周长映射
    tooth_hole_perimeter_map = {}
    if tooth_hole_data:
        tooth_hole_perimeter_map = _build_tooth_hole_perimeter_map(tooth_hole_data)
    
    # Step 6: 计算每个零件的价格（不写数据库）
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_price(
            job_id, part, wire_map, rule_map, tooth_hole_perimeter_map
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # Step 7: 批量写入数据库
    if db_updates:
        updates_for_batch = [
            {
                "job_id": d["job_id"],
                "subgraph_id": d["subgraph_id"],
                "value": d["basic_processing_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "wire_base", "basic_processing_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_rule_map(rule_prices: List[Dict]) -> Dict[str, Any]:
    """
    构建规则映射，从 min_num 字段动态解析区间
    
    Returns:
        {
            "extra_thick": [
                {
                    "min": 100, "max": 150, 
                    "min_inclusive": True, "max_inclusive": False,
                    "multiplier": 1.5
                },
                ...
            ],
            "slider": [...],
            "area_num_length": 2.0
        }
    """
    import re
    rule_map = {}
    
    for rule in rule_prices:
        sub_category = rule["sub_category"]
        price_value = rule.get("price")
        min_num = rule.get("min_num", "")
        
        # 检查 price 是否为 None
        if price_value is None:
            logger.warning(f"Skipping rule with None price for sub_category: {sub_category}")
            continue
        
        # 特殊处理 area_num：这是每个 area_num 增加的线长（mm）
        if sub_category == "area_num":
            try:
                rule_map["area_num_length"] = float(price_value)
                logger.info(f"Found area_num length per unit: {price_value} mm")
                continue
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse area_num length: {price_value}, error: {e}")
                continue
        
        if sub_category not in rule_map:
            rule_map[sub_category] = []
        
        # 从 min_num 解析区间，格式如: "[100,150)" 或 "(0,10)"
        if not min_num:
            logger.warning(f"Skipping rule without min_num for sub_category: {sub_category}")
            continue
        
        try:
            # 匹配区间格式: [或( + 数字 + , + 数字 + ]或)
            match = re.match(r'([\[\(])(\d+),\s*(\d+|[+∞∞]+)([\]\)])', str(min_num))
            
            if not match:
                logger.warning(f"Invalid min_num format: {min_num}")
                continue
            
            min_bracket = match.group(1)
            min_val = float(match.group(2))
            max_str = match.group(3)
            max_bracket = match.group(4)
            
            # 处理无穷大
            max_val = float('inf') if '+' in max_str or '∞' in max_str else float(max_str)
            
            # 倍数就是 price 字段的值
            multiplier = float(price_value)
            
            rule_map[sub_category].append({
                "min": min_val,
                "max": max_val,
                "min_inclusive": min_bracket == '[',
                "max_inclusive": max_bracket == ']',
                "multiplier": multiplier
            })
            
            logger.info(f"Parsed rule: {sub_category} {min_num} -> multiplier {multiplier}")
            
        except Exception as e:
            logger.warning(f"Failed to parse rule for {sub_category}, min_num: {min_num}, error: {e}")
    
    return rule_map


def _build_tooth_hole_perimeter_map(tooth_hole_data: Dict) -> Dict[str, Dict[str, float]]:
    """
    构建牙孔周长映射
    
    Args:
        tooth_hole_data: 来自 price_tooth_hole.calculate() 的返回结果
        
    Returns:
        {
            "subgraph_id": {
                "top_view": 123.45,
                "front_view": 67.89,
                ...
            }
        }
    """
    perimeter_map = {}
    
    if not tooth_hole_data or "results" not in tooth_hole_data:
        return perimeter_map
    
    for result in tooth_hole_data["results"]:
        subgraph_id = result.get("subgraph_id")
        perimeter_by_view = result.get("perimeter_by_view", {})
        
        if subgraph_id and perimeter_by_view:
            perimeter_map[subgraph_id] = perimeter_by_view
    
    return perimeter_map


def _get_dimension_by_view(view: str, length_mm: float, width_mm: float, thickness_mm: float) -> Tuple[float, str]:
    """
    根据视图获取对应的尺寸
    如果尺寸小于 15mm，则按 15mm 计算
    
    Returns:
        (dimension_value, dimension_name)
    """
    MIN_DIMENSION = 15.0
    
    # 处理 None 值：如果尺寸为 None，使用 MIN_DIMENSION
    if view == "top_view":
        dimension = max(thickness_mm or 0, MIN_DIMENSION)
        return dimension, "thickness_mm"
    elif view == "front_view":
        dimension = max(width_mm or 0, MIN_DIMENSION)
        return dimension, "width_mm"
    elif view == "side_view":
        dimension = max(length_mm or 0, MIN_DIMENSION)
        return dimension, "length_mm"
    else:
        return 0, "unknown"


def _in_range(value: float, range_info: dict) -> bool:
    """
    判断值是否在区间内
    
    Args:
        value: 要判断的值
        range_info: 区间信息 {"min": 100, "max": 150, "min_inclusive": True, "max_inclusive": False, "multiplier": 1.5}
    
    Returns:
        bool: 是否在区间内
    """
    if not range_info:
        return False
    
    min_val = range_info["min"]
    max_val = range_info["max"]
    min_inclusive = range_info["min_inclusive"]
    max_inclusive = range_info["max_inclusive"]
    
    # 检查最小值
    if min_inclusive:
        if value < min_val:
            return False
    else:
        if value <= min_val:
            return False
    
    # 检查最大值
    if max_val == float('inf'):
        return True
    
    if max_inclusive:
        if value > max_val:
            return False
    else:
        if value >= max_val:
            return False
    
    return True


def _apply_extra_thick_rule(dimension: float, rule_map: Dict) -> Tuple[float, str]:
    """
    应用 extra_thick 规则（动态从 rule_map 匹配区间）
    
    Returns:
        (multiplier, description)
    """
    if "extra_thick" not in rule_map:
        return 1.0, ""
    
    for rule in rule_map["extra_thick"]:
        if _in_range(dimension, rule):
            multiplier = rule["multiplier"]
            min_bracket = '[' if rule["min_inclusive"] else '('
            max_bracket = ']' if rule["max_inclusive"] else ')'
            max_str = '+∞' if rule["max"] == float('inf') else str(rule["max"])
            return multiplier, f"尺寸{dimension}在{min_bracket}{rule['min']},{max_str}{max_bracket}区间，乘{multiplier}"
    
    return 1.0, ""


def _apply_slider_rule(slider_angle: float, rule_map: Dict) -> Tuple[float, str]:
    """
    应用 slider 规则（动态从 rule_map 匹配区间）
    
    Returns:
        (multiplier, description)
    """
    if "slider" not in rule_map:
        return 1.0, ""
    
    for rule in rule_map["slider"]:
        if _in_range(slider_angle, rule):
            multiplier = rule["multiplier"]
            min_bracket = '[' if rule["min_inclusive"] else '('
            max_bracket = ']' if rule["max_inclusive"] else ')'
            max_str = '+∞' if rule["max"] == float('inf') else str(rule["max"])
            return multiplier, f"slider_angle={slider_angle}在{min_bracket}{rule['min']},{max_str}{max_bracket}区间，乘{multiplier}"
    
    return 1.0, ""


def _build_total_length_note(
    original_length: float,
    area_num: int,
    area_num_length_per_unit: float,
    tooth_hole_length: float,
    total_length: float
) -> str:
    """
    构建 total_length 的计算说明
    """
    parts = [str(original_length)]
    
    if area_num > 0 and area_num_length_per_unit > 0:
        parts.append(f"({area_num} × {area_num_length_per_unit})")
    
    if tooth_hole_length > 0:
        parts.append(f"{round(tooth_hole_length, 4)}")
    
    if len(parts) == 1:
        return parts[0]
    else:
        return " + ".join(parts) + f" = {round(total_length, 4)}"


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    wire_map: Dict,
    rule_map: Dict,
    tooth_hole_perimeter_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的线割价格
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    wire_process = part.get("wire_process")  # 例如: slow_and_one
    length_mm = part["length_mm"]
    width_mm = part["width_mm"]
    thickness_mm = part["thickness_mm"]
    metadata = part["metadata"]
    has_auto_material = part.get("has_auto_material", False)
    needs_heat_treatment = part.get("needs_heat_treatment", False)
    
    logger.info(f"Calculating price for part: {part_name} ({subgraph_id}), wire_process: {wire_process}")
    
    # 检查是否需要加牙孔周长
    tooth_hole_perimeter_by_view = {}
    if has_auto_material and needs_heat_treatment:
        tooth_hole_perimeter_by_view = tooth_hole_perimeter_map.get(subgraph_id, {})
        if tooth_hole_perimeter_by_view:
            logger.info(f"Adding tooth hole perimeter for {part_name}: {tooth_hole_perimeter_by_view}")
    
    # 根据 wire_process 匹配工艺
    wire_part = None
    status = "ok"
    
    if not wire_process:
        # wire_process 为空，尝试从 wire_map 中获取 fast_cut 作为默认工艺
        logger.warning(f"wire_process is empty for part: {part_name}, using default fast_cut")
        wire_part = wire_map.get("fast_cut")
        status = "error"
    else:
        wire_part = wire_map.get(wire_process)
        
        if not wire_part:
            # 匹配失败，尝试从 wire_map 中获取 fast_cut 作为默认工艺
            logger.warning(f"No wire process found for wire_process: {wire_process}, using default fast_cut")
            wire_part = wire_map.get("fast_cut")
            status = "error"
    
    # 如果连 fast_cut 都没有，返回错误
    if not wire_part:
        logger.error(f"Default fast_cut not found in wire_map for part: {part_name}")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "error": "未找到工艺且默认工艺fast_cut也不存在"
        }, None
    
    unit_price = float(wire_part["price"])
    process_description = wire_part["description"]  # 使用 description 而不是 name
    conditions = wire_part["conditions"]

    fast_cut_part = wire_map.get("fast_cut")
    if fast_cut_part and fast_cut_part.get("price") is not None:
        fast_cut_unit_price = float(fast_cut_part["price"])
        fast_cut_description = fast_cut_part.get("description", "fast_cut")
    else:
        fast_cut_unit_price = unit_price
        fast_cut_description = process_description
        logger.warning(
            f"fast_cut price not found for part: {part_name}, "
            f"slider detail will fallback to matched wire_process price"
        )
    
    # 解析 metadata
    if not metadata:
        logger.info(f"No metadata for {part_name}, skipping wire_base calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "basic_processing_cost": 0,
            "note": "metadata为空，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "basic_processing_cost": 0,
            "calculation_steps": [{
                "step": "检查metadata",
                "note": "metadata为空，跳过线割基础价格计算"
            }]
        }
    
    # 如果 metadata 是字符串，解析为 JSON
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception as e:
            logger.info(f"Failed to parse metadata JSON for {part_name}: {e}, skipping calculation")
            return {
                "subgraph_id": subgraph_id,
                "part_name": part_name,
                "basic_processing_cost": 0,
                "note": f"metadata JSON解析失败，跳过计算"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "basic_processing_cost": 0,
                "calculation_steps": [{
                    "step": "解析metadata",
                    "note": f"JSON解析失败: {e}，跳过线割基础价格计算"
                }]
            }
    
    # 确保 metadata 是字典类型
    if not isinstance(metadata, dict):
        logger.info(f"metadata is not a dict for {part_name}, skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "basic_processing_cost": 0,
            "note": "metadata类型错误，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "basic_processing_cost": 0,
            "calculation_steps": [{
                "step": "检查metadata类型",
                "note": "metadata不是字典类型，跳过线割基础价格计算"
            }]
        }
    
    if "wire_cut_details" not in metadata:
        logger.info(f"No wire_cut_details in metadata for {part_name}, skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "basic_processing_cost": 0,
            "note": "metadata中缺少wire_cut_details，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "basic_processing_cost": 0,
            "calculation_steps": [{
                "step": "检查wire_cut_details",
                "note": "metadata中缺少wire_cut_details，跳过线割基础价格计算"
            }]
        }
    
    wire_cut_details = metadata["wire_cut_details"]
    
    # 获取每个 area_num 增加的线长（mm）
    area_num_length_per_unit = rule_map.get("area_num_length", 0)
    
    logger.info(f"area_num_length_per_unit from rule: {area_num_length_per_unit} mm")
    
    # 计算每个 code 的价格
    calculation_steps = []
    
    # 如果有牙孔周长，添加说明步骤
    if tooth_hole_perimeter_by_view:
        calculation_steps.append({
            "step": "牙孔周长（将加到对应视图）",
            "has_auto_material": has_auto_material,
            "needs_heat_treatment": needs_heat_treatment,
            "perimeter_by_view": tooth_hole_perimeter_by_view
        })
    
    view_totals = {}  # {view: total_price}
    view_cone_flags = {}  # {view: has_cone}  记录每个视图是否有带锥加工
    
    for detail in wire_cut_details:
        code = detail.get("code")
        view = detail.get("view")
        original_total_length = detail.get("total_length", 0)
        slider_angle = detail.get("slider_angle", 0)
        instruction = detail.get("instruction", "")
        area_num = detail.get("area_num", 0)  # 从每个 detail 中获取 area_num
        cone = detail.get("cone", "f")  # 是否带锥加工，默认为 "f"
        is_slider_detail = code == "滑块"
        
        # 记录该视图是否有带锥加工
        if view and cone == "t":
            view_cone_flags[view] = True
        
        # 计算实际的 total_length：滑块使用红色面面积，其它线割沿用原始长度 + area_num补偿 + 牙孔周长
        if is_slider_detail:
            added_length = 0
            tooth_hole_length = 0
        else:
            added_length = area_num * area_num_length_per_unit if area_num and area_num_length_per_unit else 0
            tooth_hole_length = tooth_hole_perimeter_by_view.get(view, 0) if view else 0
        total_length = original_total_length + added_length + tooth_hole_length
        
        if not view or original_total_length == 0:
            calculation_steps.append({
                "code": code,
                "view": view,
                "status": "跳过",
                "reason": "view为空或total_length为0"
            })
            continue
        
        # 获取对应视图的尺寸
        dimension, dimension_name = _get_dimension_by_view(view, length_mm, width_mm, thickness_mm)
        dimension = float(dimension) if dimension else 0

        # 获取原始尺寸用于记录
        original_dimension = 0
        if dimension_name == "thickness_mm":
            original_dimension = thickness_mm
        elif dimension_name == "width_mm":
            original_dimension = width_mm
        elif dimension_name == "length_mm":
            original_dimension = length_mm

        detail_unit_price = fast_cut_unit_price if is_slider_detail else unit_price
        unit_price_source = (
            f"滑块固定使用快丝割一刀单价({fast_cut_description})"
            if is_slider_detail
            else f"零件工艺单价({process_description})"
        )

        # 基础价格计算：滑块按红色面面积计价；其它工艺保持原逻辑
        if is_slider_detail:
            base_price = total_length * detail_unit_price
            base_calculation_formula = f"{round(total_length, 4)} * {detail_unit_price}"
            calculation_note = "滑块按红色面面积计价，固定使用快丝割一刀单价"
        elif slider_angle and slider_angle != 0:
            base_price = total_length * detail_unit_price
            base_calculation_formula = f"{round(total_length, 4)} * {detail_unit_price}"
            calculation_note = "slider_angle不为空，不乘尺寸"
        else:
            base_price = total_length * dimension * detail_unit_price
            base_calculation_formula = f"{round(total_length, 4)} * {dimension} * {detail_unit_price}"
            calculation_note = "常规计算"

        
        # 构建视图与尺寸对应关系的说明
        view_dimension_mapping = {
            "top_view": "俯视图使用厚度(thickness_mm)",
            "front_view": "主视图使用宽度(width_mm)",
            "side_view": "侧视图使用长度(length_mm)"
        }
        view_dimension_note = view_dimension_mapping.get(view, "未知视图")
        
        step = {
            "code": code,
            "view": view,
            "instruction": instruction,
            "cone": cone,
            "slider_angle": slider_angle,  # 添加 slider_angle 记录
            "original_total_length": original_total_length,
            "area_num": area_num,
            "added_length": round(added_length, 4) if added_length > 0 else 0,
            "tooth_hole_length": round(tooth_hole_length, 4) if tooth_hole_length > 0 else 0,
            "total_length": round(total_length, 4),
            "total_length_note": _build_total_length_note(original_total_length, area_num, area_num_length_per_unit, tooth_hole_length, total_length),
            "original_dimension": original_dimension,
            "dimension": dimension,
            "dimension_name": dimension_name,
            "dimension_note": f"原始{original_dimension}mm，按{dimension}mm计算" if original_dimension < 15 else f"{dimension}mm",
            "view_dimension_note": view_dimension_note,
            "unit_price": detail_unit_price,
            "matched_process_unit_price": unit_price,
            "unit_price_source": unit_price_source,
            "calculation_note": calculation_note,  # 添加计算说明
            "base_calculation": f"{base_calculation_formula} = {round(base_price, 4)}",
            "base_price": round(base_price, 4),
            "multipliers": [],
            "calculation_formula": base_calculation_formula
        }

        final_price = base_price
        formula_parts = [base_calculation_formula]

        
        # 应用 extra_thick 规则
        extra_thick_mult, extra_thick_desc = _apply_extra_thick_rule(dimension, rule_map)
        if extra_thick_mult != 1.0:
            final_price *= extra_thick_mult
            formula_parts.append(f"* {extra_thick_mult}")
            step["multipliers"].append({
                "type": "extra_thick",
                "multiplier": extra_thick_mult,
                "description": extra_thick_desc
            })
        
        # 应用 slider 规则
        slider_mult, slider_desc = _apply_slider_rule(slider_angle, rule_map)
        if slider_mult != 1.0:
            final_price *= slider_mult
            formula_parts.append(f"* {slider_mult}")
            step["multipliers"].append({
                "type": "slider",
                "multiplier": slider_mult,
                "description": slider_desc
            })
        
        # 注意：cone 规则不在这里应用，而是在视图汇总后应用
        
        step["final_price"] = round(final_price, 4)
        step["complete_formula"] = " ".join(formula_parts) + f" = {round(final_price, 4)}"
        step[f"{code}_price"] = round(final_price, 4)
        
        calculation_steps.append(step)
        
        # 累加到视图总价
        if view not in view_totals:
            view_totals[view] = 0
        view_totals[view] += final_price
    
    # 应用视图级别的 cone 规则
    view_totals_after_cone = {}
    for view, total in view_totals.items():
        if view_cone_flags.get(view, False):
            # 该视图有带锥加工，乘 1.5
            view_totals_after_cone[view] = total * 1.5
        else:
            view_totals_after_cone[view] = total
    
    # 计算总价
    basic_processing_cost = sum(view_totals_after_cone.values())
    
    # 添加汇总步骤
    calculation_steps.append({
        "step": "视图汇总（应用cone规则前）",
        "view_totals": {k: round(v, 4) for k, v in view_totals.items()}
    })
    
    # 添加 cone 规则应用步骤
    if any(view_cone_flags.values()):
        cone_details = []
        for view in view_totals.keys():
            if view_cone_flags.get(view, False):
                cone_details.append({
                    "view": view,
                    "before_cone": round(view_totals[view], 4),
                    "after_cone": round(view_totals_after_cone[view], 4),
                    "multiplier": 1.5
                })
        
        calculation_steps.append({
            "step": "应用视图级别cone规则",
            "cone_details": cone_details
        })
    
    calculation_steps.append({
        "step": "视图汇总（应用cone规则后）",
        "view_totals_after_cone": {k: round(v, 4) for k, v in view_totals_after_cone.items()}
    })
    
    calculation_steps.append({
        "step": "最终总价",
        "basic_processing_cost": round(basic_processing_cost, 4)
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "process_description": process_description,
        "conditions": conditions,
        "basic_processing_cost": round(basic_processing_cost, 4),
        "status": status
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "basic_processing_cost": basic_processing_cost,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _update_calculation_details(
    job_id: str,
    subgraph_id: str,
    basic_processing_cost: float,
    new_steps: List[Dict]
):
    """
    更新 processing_cost_calculation_details 表（保留用于向后兼容）
    """
    await batch_upsert_with_steps(
        [{
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "value": basic_processing_cost,
            "steps": new_steps
        }],
        "wire_base",
        "basic_processing_cost"
    )


# 便捷同步调用接口


# 便捷同步调用接口
def calculate_sync(search_data: Dict[str, Any], job_id: str = None, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    """同步版本的计算接口"""
    return asyncio.run(calculate(search_data, job_id, subgraph_ids))


# 测试入口
if __name__ == "__main__":
    import sys
    import os
    
    # 添加项目根目录到Python路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 3:
        print("Usage: python price_wire_base.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = calculate_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 计算结果 (job_id: {job_id}) ===")
    for result in results["results"]:
        if "error" in result:
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  错误: {result['error']}")
        else:
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  工艺: {result['process_description']} ({result['conditions']})")
            print(f"  基础加工费: {result['basic_processing_cost']} 元")
            print(f"  状态: {result['status']}")
