"""
水磨斜面耗时计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（water_mill, has_auto_material, has_material_preparation）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 根据 bevel 值大小选择对应价格：<=10 用 15，>10 用 20
5. bevel_cost 直接等于选中的价格（不相乘）
6. 更新 processing_cost_calculation_details 表的 bevel_cost
"""
from typing import List, Dict, Any
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps
from ._water_mill_helper import determine_mill_type

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_water_mill_bevel_cost",
    "description": "计算水磨斜面耗时费：根据零件water_mill数据和价格配置计算斜面费用",
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
    计算水磨斜面耗时费
    
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
    
    logger.info(f"Calculating water mill bevel cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
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
                "value": d["bevel_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_bevel", "bevel_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(water_mill_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建价格映射，从 min_num 字段动态解析区间
    
    Returns:
        {
            "bevel_prices": [
                {
                    "price": 15, 
                    "unit": "min",
                    "min": 0, "max": 10,
                    "min_inclusive": False, "max_inclusive": False
                },
                {
                    "price": 20, 
                    "unit": "min",
                    "min": 10, "max": 9999,
                    "min_inclusive": True, "max_inclusive": False
                }
            ]
        }
    """
    import re
    price_map = {
        "bevel_prices": []
    }
    
    # 处理小磨床价格
    for price in water_mill_data.get("s_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        min_num = price.get("min_num", "")
        
        if sub_category == "bevel":
            try:
                price_float = float(price_value)
                
                # 解析 min_num 区间，格式如: "(0,10)" 或 "[10,9999)"
                range_info = None
                if min_num:
                    match = re.match(r'([\[\(])(\d+),\s*(\d+|[+∞∞]+)([\]\)])', str(min_num))
                    if match:
                        min_bracket = match.group(1)
                        min_val = float(match.group(2))
                        max_str = match.group(3)
                        max_bracket = match.group(4)
                        
                        max_val = float('inf') if '+' in max_str or '∞' in max_str else float(max_str)
                        
                        range_info = {
                            "min": min_val,
                            "max": max_val,
                            "min_inclusive": min_bracket == '[',
                            "max_inclusive": max_bracket == ']'
                        }
                
                price_entry = {
                    "price": price_float,
                    "unit": unit
                }
                
                if range_info:
                    price_entry.update(range_info)
                
                price_map["bevel_prices"].append(price_entry)
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse bevel price: {price_value}, error: {e}")
    
    # 按价格排序，确保小的在前
    price_map["bevel_prices"].sort(key=lambda x: x["price"])
    
    return price_map


def _in_range(value: float, range_info: dict) -> bool:
    """
    判断值是否在区间内
    
    Args:
        value: 要判断的值
        range_info: 区间信息，必须包含 min, max, min_inclusive, max_inclusive
    
    Returns:
        bool: 是否在区间内
    """
    if "min" not in range_info or "max" not in range_info:
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


def _get_bevel_unit_price(bevel_count: int, price_map: Dict) -> tuple[float, str]:
    """
    根据 bevel 数量动态获取对应的单价
    
    Args:
        bevel_count: bevel 数量
        price_map: 价格映射
    
    Returns:
        tuple: (unit_price, unit)
    """
    bevel_prices = price_map.get("bevel_prices", [])
    
    if not bevel_prices:
        return 0, ""
    
    # 如果只有一个价格，直接返回
    if len(bevel_prices) == 1:
        return bevel_prices[0]["price"], bevel_prices[0]["unit"]
    
    # 遍历价格列表，找到匹配的区间
    for price_info in bevel_prices:
        if _in_range(bevel_count, price_info):
            return price_info["price"], price_info["unit"]
    
    # 如果没有匹配的，返回第一个价格作为默认值
    logger.warning(f"No matching price range for bevel_count={bevel_count}, using first price")
    return bevel_prices[0]["price"], bevel_prices[0]["unit"]


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨斜面耗时费
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    has_auto_material = part.get("has_auto_material", False)
    has_material_preparation = part.get("has_material_preparation")
    water_mill = part.get("water_mill")
    
    logger.info(f"Calculating bevel cost for part: {part_name} ({subgraph_id})")
    
    # 初始化计算步骤
    calculation_steps = []
    
    # 判断水磨类型
    mill_type = determine_mill_type(has_auto_material, has_material_preparation)
    
    # 解析 water_mill
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
            "bevel_cost": 0,
            "note": "无water_mill_details数据"
        }, None
    
    water_mill_details = water_mill["water_mill_details"]
    
    # 获取 bevel 数据（可能是单个数值或数组）
    bevel_data = None
    for detail in water_mill_details:
        if "bevel" in detail:
            bevel_data = detail.get("bevel")
            break
    
    # 处理 bevel 数据，统一转换为列表
    bevel_values = []
    if bevel_data is None or bevel_data == 0:
        logger.info(f"No bevel for {part_name}")
        calculation_steps.append({
            "step": "检查bevel数据",
            "bevel_data": bevel_data,
            "note": "bevel数量为0或不存在"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "bevel_cost": 0,
            "note": "bevel数量为0或不存在"
        }, None
    elif isinstance(bevel_data, list):
        # 如果是数组，过滤掉0值
        bevel_values = [v for v in bevel_data if v and v != 0]
    else:
        # 如果是单个数值
        if bevel_data != 0:
            bevel_values = [bevel_data]
    
    if not bevel_values:
        logger.info(f"No valid bevel values for {part_name}")
        calculation_steps.append({
            "step": "检查bevel数据",
            "bevel_data": bevel_data,
            "note": "bevel数组为空或全为0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "bevel_cost": 0,
            "note": "bevel数组为空或全为0"
        }, None
    
    # Step 1: 判断水磨类型
    calculation_steps.append({
        "step": "判断水磨类型",
        "has_auto_material": has_auto_material,
        "has_material_preparation": has_material_preparation,
        "mill_type": mill_type,
        "reason": f"has_auto_material={has_auto_material} 或 has_material_preparation={has_material_preparation}"
    })
    
    # Step 2: 只有小磨床才计算斜面耗时
    if mill_type != "s_water_mill":
        calculation_steps.append({
            "step": "判断是否计算",
            "note": "斜面耗时仅适用于小磨床，当前为大水磨，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "bevel_cost": 0,
            "note": "大水磨不计算斜面耗时"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "bevel_cost": 0,
            "calculation_steps": calculation_steps
        }
    
    # Step 3: 遍历每个 bevel 值，分别计算费用
    total_bevel_cost = 0
    bevel_details = []
    
    for idx, bevel_value in enumerate(bevel_values, 1):
        bevel_unit_price, unit = _get_bevel_unit_price(bevel_value, price_map)
        price_rule = "<=10 用较小单价" if bevel_value <= 10 else ">10 用较大单价"
        
        bevel_details.append({
            "index": idx,
            "bevel_value": bevel_value,
            "price_rule": price_rule,
            "unit_price": bevel_unit_price,
            "unit": unit
        })
        
        total_bevel_cost += bevel_unit_price
        
        calculation_steps.append({
            "step": f"计算第{idx}个bevel费用",
            "bevel_value": bevel_value,
            "price_rule": price_rule,
            "unit_price": bevel_unit_price,
            "unit": unit
        })
    
    # Step 4: 汇总斜面耗时费
    calculation_steps.append({
        "step": "汇总斜面耗时费",
        "bevel_values": bevel_values,
        "bevel_details": bevel_details,
        "total_bevel_cost": round(total_bevel_cost, 2),
        "formula": " + ".join([f"{d['unit_price']}" for d in bevel_details]) + f" = {round(total_bevel_cost, 2)}"
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "bevel_values": bevel_values,
        "bevel_details": bevel_details,
        "bevel_cost": round(total_bevel_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "bevel_cost": total_bevel_cost,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


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
        print("Usage: python price_water_mill_bevel_cost.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
