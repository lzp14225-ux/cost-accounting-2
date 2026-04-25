"""
水磨零件费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（尺寸, water_mill, has_auto_material, has_material_preparation）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 只有大水磨且为零件（不是板也不是长条）时才进行计算
5. 根据 grinding 值（研磨面数）和尺寸确定费用
6. 更新 processing_cost_calculation_details 表的 component_cost
"""
from typing import List, Dict, Any
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps
from ._water_mill_helper import determine_mill_type, determine_part_type

logger = logging.getLogger(__name__)


def _parse_price_value(price_value) -> float:
    """
    解析价格值，支持多种格式：
    - 数字：1, 1.5, 0.8
    - 分数字符串："1/2", "4/5"
    
    Args:
        price_value: 价格值（可能是数字或字符串）
    
    Returns:
        float: 解析后的浮点数
    
    Raises:
        ValueError: 无法解析时抛出异常
    """
    if price_value is None:
        raise ValueError("Price value is None")
    
    # 如果已经是数字类型，直接转换
    if isinstance(price_value, (int, float)):
        return float(price_value)
    
    # 转换为字符串处理
    price_str = str(price_value).strip()
    
    # 尝试直接转换为浮点数
    try:
        return float(price_str)
    except ValueError:
        pass
    
    # 尝试解析分数格式（如 "1/2"）
    if "/" in price_str:
        try:
            parts = price_str.split("/")
            if len(parts) == 2:
                numerator = float(parts[0].strip())
                denominator = float(parts[1].strip())
                if denominator == 0:
                    raise ValueError("Denominator cannot be zero")
                return numerator / denominator
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid fraction format: {price_str}") from e
    
    raise ValueError(f"Cannot parse price value: {price_str}")


def _parse_size_range(range_value) -> dict | None:
    """
    解析尺寸区间，支持 "[500,800)"、"(0,200)"、"[1500,9999)"、"[200,+∞)"。
    """
    import re

    if not range_value:
        return None

    range_str = str(range_value).strip()
    match = re.match(r'([\[\(])\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?|\+|∞|\+∞)\s*([\]\)])', range_str)
    if not match:
        return None

    max_str = match.group(3)
    max_val = float('inf') if max_str in ("+", "∞", "+∞") else float(max_str)

    return {
        "min": float(match.group(2)),
        "max": max_val,
        "min_inclusive": match.group(1) == '[',
        "max_inclusive": match.group(4) == ']'
    }


# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_water_mill_component_price",
    "description": "计算水磨零件费：根据零件研磨面数和尺寸计算零件加工费用",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 water_mill"
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
    "needs": ["base_itemcode", "water_mill"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算水磨零件费
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 water_mill
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    water_mill_data = search_data["water_mill"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating water mill component cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 3: 构建价格映射
    price_map = _build_price_map(water_mill_data)
    
    # Step 4: 计算每个零件的价格（不写数据库）
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_price(
            job_id, part, price_map
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # Step 5: 批量写入数据库
    if db_updates:
        updates_for_batch = [
            {
                "job_id": d["job_id"],
                "subgraph_id": d["subgraph_id"],
                "value": d["component_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_component", "component_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(water_mill_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建价格映射，从 min_num 字段动态解析研磨面数和尺寸区间
    
    Returns:
        {
            "grinding_rules": [
                {
                    "grinding_faces": 6,
                    "price": 1,
                    "unit": "小时",
                    "size_range": {"min": 0, "max": 200, "min_inclusive": False, "max_inclusive": False}
                },
                {
                    "grinding_faces": 6,
                    "price": 1.5,
                    "unit": "小时",
                    "size_range": {"min": 200, "max": 9999, "min_inclusive": True, "max_inclusive": False}
                },
                {
                    "grinding_faces": 4,
                    "price": 0.8,
                    "unit": None,
                    "size_range": None  # 无尺寸限制，是倍数
                },
                {
                    "grinding_faces": 2,
                    "price": 0.5,
                    "unit": None,
                    "size_range": None  # 无尺寸限制，是倍数
                }
            ]
        }
    """
    import re
    price_map = {
        "grinding_rules": [],
        "component_four_rules": []
    }
    
    # 处理大水磨价格
    for price in water_mill_data.get("l_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        min_num = price.get("min_num", "")
        
        if sub_category == "component":
            try:
                # 尝试解析价格值（支持分数格式如 "1/2"）
                price_float = _parse_price_value(price_value)
                
                # 解析 min_num
                # 格式1: "6, (0,200)" - 表示6面研磨，尺寸在(0,200)区间
                # 格式2: "4" - 表示4面研磨，无尺寸限制
                grinding_faces = None
                size_range = None
                
                if min_num:
                    min_num_str = str(min_num).strip()
                    
                    # 尝试匹配 "数字, 区间" 格式
                    match = re.match(r'(\d+)\s*,\s*(.+)', min_num_str)
                    if match:
                        grinding_faces = int(match.group(1))
                        size_range = _parse_size_range(match.group(2))
                        if not size_range:
                            logger.warning(f"Failed to parse component size range: {min_num}")
                            continue
                    else:
                        # 尝试匹配纯数字格式
                        try:
                            grinding_faces = int(min_num_str)
                        except ValueError:
                            logger.warning(f"Failed to parse min_num: {min_num}")
                            continue
                
                if grinding_faces:
                    price_map["grinding_rules"].append({
                        "grinding_faces": grinding_faces,
                        "price": price_float,
                        "unit": unit,
                        "size_range": size_range
                    })
                    
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse component price: {price_value}, error: {e}")

        elif sub_category == "component_four":
            try:
                price_float = _parse_price_value(price_value)
                size_range = _parse_size_range(min_num)
                if not size_range:
                    logger.warning(f"Failed to parse component_four size range: {min_num}")
                    continue

                price_map["component_four_rules"].append({
                    "price": price_float,
                    "unit": unit,
                    "size_range": size_range
                })
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse component_four price: {price_value}, error: {e}")

    price_map["component_four_rules"] = sorted(
        price_map["component_four_rules"],
        key=lambda item: item["size_range"]["min"]
    )
    
    return price_map


def _in_range(value: float, range_info: dict) -> bool:
    """
    判断值是否在区间内
    
    Args:
        value: 要判断的值
        range_info: 区间信息 {"min": 0, "max": 200, "min_inclusive": False, "max_inclusive": False}
    
    Returns:
        bool: 是否在区间内
    """
    if not range_info or "min" not in range_info or "max" not in range_info:
        return False
    
    min_val = range_info["min"]
    max_val = range_info["max"]
    min_inclusive = range_info.get("min_inclusive", False)
    max_inclusive = range_info.get("max_inclusive", False)
    
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


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨零件费
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    length_mm = part.get("length_mm") or 0
    width_mm = part.get("width_mm") or 0
    thickness_mm = part.get("thickness_mm") or 0
    has_auto_material = part.get("has_auto_material", False)
    has_material_preparation = part.get("has_material_preparation")
    water_mill = part.get("water_mill")
    
    logger.info(f"Calculating component cost for part: {part_name} ({subgraph_id})")
    
    # 初始化计算步骤
    calculation_steps = []
    
    # Step 1: 判断水磨类型
    mill_type = determine_mill_type(has_auto_material, has_material_preparation)
    
    calculation_steps.append({
        "step": "判断水磨类型",
        "has_auto_material": has_auto_material,
        "has_material_preparation": has_material_preparation,
        "mill_type": mill_type,
        "reason": f"has_auto_material={has_auto_material} 或 has_material_preparation={has_material_preparation}"
    })
    
    # Step 2: 只有大水磨才计算零件费
    if mill_type != "l_water_mill":
        calculation_steps.append({
            "step": "判断是否计算",
            "note": "零件费仅适用于大水磨，当前为小磨床，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "component_cost": 0,
            "note": "小磨床不计算零件费"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "component_cost": 0,
            "calculation_steps": calculation_steps
        }
    
    # Step 3: 判断零件类型
    part_type = determine_part_type(length_mm, width_mm, thickness_mm)
    dimensions = sorted([length_mm, width_mm, thickness_mm])
    
    calculation_steps.append({
        "step": "判断大水磨零件类型",
        "dimensions": {
            "length_mm": length_mm,
            "width_mm": width_mm,
            "thickness_mm": thickness_mm,
            "sorted": dimensions
        },
        "part_type": part_type,
        "reason": _get_part_type_reason(dimensions, part_type)
    })
    
    # Step 4: 只有零件才计算零件费
    if part_type != "component":
        calculation_steps.append({
            "step": "判断是否为零件",
            "part_type": part_type,
            "note": "当前零件不是零件类型（是板或长条），不计算零件费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "part_type": part_type,
            "component_cost": 0,
            "note": "不是零件类型"
        }, None
    
    # Step 5: 解析 water_mill 获取 grinding 值
    if isinstance(water_mill, str):
        try:
            water_mill = json.loads(water_mill)
        except Exception as e:
            logger.error(f"Failed to parse water_mill JSON: {e}")
            water_mill = {}
    
    if not water_mill or "water_mill_details" not in water_mill:
        logger.warning(f"No water_mill_details for {part_name}")
        calculation_steps.append({
            "step": "检查数据",
            "note": "无water_mill_details数据"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "component_cost": 0,
            "note": "无water_mill_details数据"
        }, None
    
    water_mill_details = water_mill["water_mill_details"]
    
    # 获取 grinding 值
    grinding_value = 0
    for detail in water_mill_details:
        if "grinding" in detail:
            grinding_value = detail.get("grinding", 0)
            break
    
    if grinding_value == 0:
        logger.info(f"No grinding value for {part_name}")
        calculation_steps.append({
            "step": "检查grinding数据",
            "grinding_value": grinding_value,
            "note": "grinding值为0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "component_cost": 0,
            "note": "grinding值为0"
        }, None
    
    calculation_steps.append({
        "step": "获取研磨面数",
        "grinding": grinding_value,
        "note": f"{grinding_value}面研磨"
    })
    
    # Step 6: 根据 grinding 值动态计算费用
    component_cost = 0
    grinding_rules = price_map.get("grinding_rules", [])
    
    if not grinding_rules:
        logger.warning(f"No grinding rules found for {part_name}")
        calculation_steps.append({
            "step": "查找研磨规则",
            "note": "未找到研磨规则配置"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "component_cost": 0,
            "note": "未找到研磨规则配置"
        }, None
    
    # 获取长宽的最大值（用于原有6面基础规则判断）
    max_length_width = max(length_mm, width_mm)
    # 获取最长边（用于 component_four 区间规则判断）
    max_dimension = max(length_mm, width_mm, thickness_mm)
    
    # 查找匹配的规则
    # 逻辑：
    # 1. 如果是6面研磨，直接查找有尺寸限制的规则（unit="小时"）
    # 2. 如果是4面研磨，优先用 component_four 按最长边命中的基础时间，再乘以4面倍数
    # 3. 如果是2面研磨，或4面未命中 component_four，先找6面研磨的基础时间，再乘以倍数（unit=None）
    
    matched_rule = None
    base_rule = None  # 6面研磨的基础规则
    multiplier_rule = None  # 2面或4面的倍数规则
    
    # 先找到6面研磨在当前尺寸下的基础时间
    for rule in grinding_rules:
        if rule["grinding_faces"] == 6 and rule.get("size_range"):
            if _in_range(max_length_width, rule["size_range"]):
                base_rule = rule
                break
    
    if not base_rule:
        logger.warning(f"No base 6-face grinding rule found for max_length_width={max_length_width}")
        calculation_steps.append({
            "step": "查找6面研磨基础规则",
            "max_length_width": max_length_width,
            "note": "未找到6面研磨的基础规则"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "grinding": grinding_value,
            "component_cost": 0,
            "note": "未找到6面研磨的基础规则"
        }, None
    
    # 判断当前研磨面数
    if grinding_value == 6:
        # 6面研磨直接使用基础规则
        component_cost = base_rule["price"]
        
        size_range = base_rule["size_range"]
        min_bracket = '[' if size_range["min_inclusive"] else '('
        max_bracket = ']' if size_range["max_inclusive"] else ')'
        max_str = '+∞' if size_range["max"] == float('inf') else str(size_range["max"])
        
        calculation_steps.append({
            "step": f"计算{grinding_value}面研磨费用",
            "max_length_width": max_length_width,
            "size_range": f"{min_bracket}{size_range['min']},{max_str}{max_bracket}",
            "component_cost": component_cost,
            "unit": base_rule.get("unit", "小时")
        })
    else:
        # 2面或4面研磨，需要找到倍数规则
        for rule in grinding_rules:
            if rule["grinding_faces"] == grinding_value and not rule.get("size_range"):
                multiplier_rule = rule
                break
        
        if not multiplier_rule:
            logger.warning(f"No multiplier rule found for grinding_value={grinding_value}")
            calculation_steps.append({
                "step": "查找倍数规则",
                "grinding_value": grinding_value,
                "note": f"未找到{grinding_value}面研磨的倍数规则"
            })
            return {
                "subgraph_id": subgraph_id,
                "part_name": part_name,
                "grinding": grinding_value,
                "component_cost": 0,
                "note": f"未找到{grinding_value}面研磨的倍数规则"
            }, None
        
        component_four_rule = None
        if grinding_value == 4:
            for rule in price_map.get("component_four_rules", []):
                if _in_range(max_dimension, rule["size_range"]):
                    component_four_rule = rule
                    break

        if component_four_rule:
            base_time = component_four_rule["price"]
            base_time_source = "component_four"
            active_range = component_four_rule["size_range"]
        else:
            base_time = base_rule["price"]
            base_time_source = "6面研磨基础规则"
            active_range = base_rule["size_range"]

        # 计算：基础时间 * 研磨面数倍数
        component_cost = base_time * multiplier_rule["price"]
        
        size_range = active_range
        min_bracket = '[' if size_range["min_inclusive"] else '('
        max_bracket = ']' if size_range["max_inclusive"] else ')'
        max_str = '+∞' if size_range["max"] == float('inf') else str(size_range["max"])
        
        calculation_steps.append({
            "step": f"计算{grinding_value}面研磨费用",
            "max_length_width": max_length_width,
            "max_dimension": max_dimension,
            "base_time_source": base_time_source,
            "size_range": f"{min_bracket}{size_range['min']},{max_str}{max_bracket}",
            "base_time": base_time,
            "multiplier": multiplier_rule["price"],
            "formula": f"{base_time} × {multiplier_rule['price']}",
            "component_cost": round(component_cost, 2),
            "unit": "小时",
            "note": f"先取基础时间({base_time}小时，来源：{base_time_source})，再乘以{grinding_value}面研磨倍数({multiplier_rule['price']})"
        })
    
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "part_type": part_type,
        "grinding": grinding_value,
        "component_cost": round(component_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "component_cost": component_cost,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


def _get_part_type_reason(dimensions: List[float], part_type: str) -> str:
    """
    获取零件类型判断原因
    """
    min_dim, mid_dim, max_dim = dimensions
    
    if part_type == "plate":
        return f"中间值{mid_dim}mm > 250mm，判定为板"
    elif part_type == "long_strip":
        return f"最大值{max_dim}mm >= 中间值{mid_dim}mm * 2，判定为长条"
    else:
        return f"不满足板和长条条件，判定为零件"


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
        print("Usage: python price_water_mill_component.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
