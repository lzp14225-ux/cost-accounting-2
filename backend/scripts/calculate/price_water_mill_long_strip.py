"""
水磨长条费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（尺寸, has_auto_material, has_material_preparation）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 只有大水磨且为长条时才进行计算
5. 根据最长边的长度确定单价（小时/件）
6. 返回单价作为长条费
7. 更新 processing_cost_calculation_details 表的 long_strip_cost
"""
from typing import List, Dict, Any
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps
from ._water_mill_helper import determine_mill_type, determine_part_type

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_water_mill_long_strip_price",
    "description": "计算水磨长条费：根据零件最长边长度和数量计算长条加工时间费用",
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
    计算水磨长条费
    
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
    
    logger.info(f"Calculating water mill long strip cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
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
                "value": d["long_strip_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_long_strip", "long_strip_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(water_mill_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    构建价格映射，从 min_num 字段解析价格区间
    
    Returns:
        List[Dict]: 按区间最小值排序的长条价格列表
        [
            {"price": 0.8, "range_min": 0, "range_max": 300, "min_inclusive": False, "max_inclusive": False, "unit": "小时/件"},
            {"price": 1, "range_min": 300, "range_max": 500, "min_inclusive": True, "max_inclusive": False, "unit": "小时/件"},
            ...
        ]
    """
    import re
    price_list = []
    
    l_water_mill_prices = water_mill_data.get("l_water_mill_prices", [])
    logger.info(f"Building price map from {len(l_water_mill_prices)} L_water_mill prices")
    
    # 处理大水磨价格
    for price in l_water_mill_prices:
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        min_num = price.get("min_num", "")
        
        if sub_category == "long_strip":
            try:
                # 从 min_num 解析区间，格式如: "(0, 300)" 或 "[1000, +∞)"
                logger.info(f"Processing long_strip price: value={price_value}, unit={unit}, min_num='{min_num}' (type: {type(min_num).__name__})")
                
                if not min_num:
                    logger.warning(f"Skipping long_strip price without min_num: {price_value}")
                    continue
                
                # 匹配区间格式: [或( + 数字 + , + 数字 + ]或)
                match = re.match(r'([\[\(])(\d+)\s*,\s*(\d+|[+∞∞]+)([\]\)])', str(min_num))
                
                if match:
                    min_bracket = match.group(1)
                    range_min = float(match.group(2))
                    range_max_str = match.group(3)
                    max_bracket = match.group(4)
                    
                    # 处理无穷大
                    range_max = float('inf') if '+' in range_max_str or '∞' in range_max_str else float(range_max_str)
                    
                    price_info = {
                        "price": float(price_value),
                        "range_min": range_min,
                        "range_max": range_max,
                        "min_inclusive": min_bracket == '[',
                        "max_inclusive": max_bracket == ']',
                        "unit": unit
                    }
                    price_list.append(price_info)
                    logger.info(f"Successfully parsed: {min_bracket}{range_min}, {range_max_str}{max_bracket} -> price={price_value}")
                else:
                    logger.warning(f"Failed to parse long_strip min_num format: '{min_num}'")
                    
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse long_strip price: {price_value}, min_num: {min_num}, error: {e}")
    
    # 按区间最小值排序
    price_list.sort(key=lambda x: x["range_min"])
    
    logger.info(f"Built price map with {len(price_list)} long_strip price ranges")
    for i, p in enumerate(price_list):
        min_b = '[' if p['min_inclusive'] else '('
        max_b = ']' if p['max_inclusive'] else ')'
        max_v = '+∞' if p['range_max'] == float('inf') else p['range_max']
        logger.info(f"  Range {i+1}: {min_b}{p['range_min']}, {max_v}{max_b} -> {p['price']} {p['unit']}")
    
    return price_list


def _in_range(value: float, range_info: dict) -> bool:
    """
    判断值是否在区间内
    
    Args:
        value: 要判断的值
        range_info: 区间信息 {"range_min": 0, "range_max": 300, "min_inclusive": False, "max_inclusive": False}
    
    Returns:
        bool: 是否在区间内
    """
    if not range_info or "range_min" not in range_info or "range_max" not in range_info:
        return False
    
    min_val = range_info["range_min"]
    max_val = range_info["range_max"]
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


def _get_unit_price_by_length(max_length: float, price_list: List[Dict[str, Any]]) -> tuple[float, str]:
    """
    根据最长边长度从价格列表中动态获取单价（支持开闭区间）
    
    Args:
        max_length: 最长边长度（mm）
        price_list: 价格列表，包含 range_min, range_max, min_inclusive, max_inclusive, price
    
    Returns:
        tuple: (单价, 价格区间说明)
    """
    # 遍历价格列表，找到匹配的区间
    for price_info in price_list:
        if _in_range(max_length, price_info):
            range_min = price_info["range_min"]
            range_max = price_info["range_max"]
            min_bracket = '[' if price_info["min_inclusive"] else '('
            max_bracket = ']' if price_info["max_inclusive"] else ')'
            range_max_str = '+∞' if range_max == float('inf') else str(range_max)
            
            range_desc = f"{min_bracket}{range_min}, {range_max_str}{max_bracket}"
            return price_info["price"], range_desc
    
    # 如果没找到匹配的区间，返回最后一个价格（通常是最大区间）
    if price_list:
        last_price = price_list[-1]
        range_min = last_price["range_min"]
        range_max = last_price["range_max"]
        min_bracket = '[' if last_price["min_inclusive"] else '('
        max_bracket = ']' if last_price["max_inclusive"] else ')'
        range_max_str = '+∞' if range_max == float('inf') else str(range_max)
        
        range_desc = f"{min_bracket}{range_min}, {range_max_str}{max_bracket}"
        logger.warning(f"Length {max_length} not in any range, using last price: {last_price['price']}")
        return last_price["price"], range_desc
    
    # 如果价格列表为空，返回0
    logger.error("Price list is empty, returning 0")
    return 0, "无价格数据"


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: List[Dict[str, Any]]
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨长条费
    
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
    quantity = part.get("quantity") or 1
    
    logger.info(f"Calculating long strip cost for part: {part_name} ({subgraph_id})")
    
    # 计算步骤
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
    
    # Step 2: 只有大水磨才计算长条费
    if mill_type != "l_water_mill":
        calculation_steps.append({
            "step": "判断是否计算",
            "note": "长条费仅适用于大水磨，当前为小磨床，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "long_strip_cost": 0,
            "note": "小磨床不计算长条费"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "long_strip_cost": 0,
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
    
    # Step 4: 只有长条才计算长条费
    if part_type != "long_strip":
        calculation_steps.append({
            "step": "判断是否为长条",
            "part_type": part_type,
            "note": "当前零件不是长条，不计算长条费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "part_type": part_type,
            "long_strip_cost": 0,
            "note": "不是长条类型"
        }, None
    
    # Step 5: 获取最长边
    max_length = max(length_mm, width_mm, thickness_mm)
    
    calculation_steps.append({
        "step": "获取最长边",
        "length_mm": length_mm,
        "width_mm": width_mm,
        "thickness_mm": thickness_mm,
        "max_length": max_length
    })
    
    # Step 5.1: 检查最长边是否为0
    if max_length == 0:
        calculation_steps.append({
            "step": "检查最长边",
            "max_length": max_length,
            "note": "最长边为0，跳过计算，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "part_type": part_type,
            "max_length": max_length,
            "long_strip_cost": 0,
            "note": "最长边为0，无法计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "long_strip_cost": 0,
            "calculation_steps": calculation_steps
        }
    
    # Step 6: 根据最长边获取单价
    unit_price, range_desc = _get_unit_price_by_length(max_length, price_map)
    
    calculation_steps.append({
        "step": "确定单价",
        "max_length": max_length,
        "range": range_desc,
        "unit_price": unit_price,
        "unit": "小时/件"
    })
    
    # Step 7: 计算长条费（时间花费）
    long_strip_cost = unit_price
    
    calculation_steps.append({
        "step": "计算长条费",
        "unit_price": unit_price,
        "long_strip_cost": round(long_strip_cost, 2),
        "note": "单位为小时/件"
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "part_type": part_type,
        "max_length": max_length,
        "unit_price": unit_price,
        "long_strip_cost": round(long_strip_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "long_strip_cost": long_strip_cost,
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
        print("Usage: python price_water_mill_long_strip.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
