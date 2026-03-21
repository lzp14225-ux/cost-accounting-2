"""
水磨线头费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（尺寸, water_mill, has_auto_material, has_material_preparation）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 计算线头费：thread_ends * price
5. 更新 processing_cost_calculation_details 表的 thread_ends_cost
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
    "name": "calculate_water_mill_thread_ends_price",
    "description": "计算水磨线头费：根据零件water_mill数据和价格配置计算线头费用",
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
    计算水磨线头费
    
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
    
    logger.info(f"Calculating water mill thread ends price for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
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
                "value": d["thread_ends_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_thread_ends", "thread_ends_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(water_mill_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建价格映射
    
    Returns:
        {
            "s_water_mill": {
                "thread_ends": 4,
                ...
            },
            "l_water_mill": {
                "plate": [...],
                "long_strip": [...],
                "component": [...]
            }
        }
    """
    price_map = {
        "s_water_mill": {},
        "l_water_mill": {
            "plate": [],
            "long_strip": [],
            "component": []
        }
    }
    
    # 处理小磨床价格
    for price in water_mill_data.get("s_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        
        try:
            price_map["s_water_mill"][sub_category] = {
                "price": float(price_value),
                "unit": unit
            }
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse S water mill price for {sub_category}: {price_value}, error: {e}")
    
    # 处理大水磨价格
    for price in water_mill_data.get("l_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        
        if sub_category in ["plate", "long_strip", "component"]:
            try:
                price_map["l_water_mill"][sub_category].append({
                    "price": price_value,
                    "unit": unit
                })
            except Exception as e:
                logger.warning(f"Failed to parse L water mill price for {sub_category}: {price_value}, error: {e}")
    
    return price_map





async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨线头费
    
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
    
    logger.info(f"Calculating thread ends cost for part: {part_name} ({subgraph_id})")
    
    # 初始化计算步骤
    calculation_steps = []
    
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
            "thread_ends_cost": 0,
            "note": "无water_mill_details数据"
        }, None
    
    water_mill_details = water_mill["water_mill_details"]
    
    # 获取 thread_ends 数量
    thread_ends_count = 0
    for detail in water_mill_details:
        if "thread_ends" in detail:
            thread_ends_count = detail.get("thread_ends", 0)
            break
    
    if thread_ends_count == 0:
        logger.info(f"No thread_ends for {part_name}")
        calculation_steps.append({
            "step": "检查thread_ends数据",
            "thread_ends_count": thread_ends_count,
            "note": "thread_ends数量为0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "thread_ends_cost": 0,
            "note": "thread_ends数量为0"
        }, None
    
    # Step 1: 判断水磨类型
    mill_type = determine_mill_type(has_auto_material, has_material_preparation)
    
    calculation_steps.append({
        "step": "判断水磨类型",
        "has_auto_material": has_auto_material,
        "has_material_preparation": has_material_preparation,
        "mill_type": mill_type,
        "reason": f"has_auto_material={has_auto_material} 或 has_material_preparation={has_material_preparation}"
    })
    
    # Step 2: 如果是大水磨，判断零件类型
    part_type = None
    if mill_type == "l_water_mill":
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
    
    # Step 3: 获取线头费单价（只有小磨床才计算）
    thread_ends_unit_price = 0
    
    if mill_type == "s_water_mill":
        # 小磨床直接取 thread_ends 价格
        thread_ends_info = price_map["s_water_mill"].get("thread_ends", {})
        thread_ends_unit_price = thread_ends_info.get("price", 0)
        unit = thread_ends_info.get("unit", "")
        
        calculation_steps.append({
            "step": "获取小磨床线头费单价",
            "unit_price": thread_ends_unit_price,
            "unit": unit
        })
    else:
        # 大水磨暂时没有线头费配置，设为0
        calculation_steps.append({
            "step": "获取大水磨线头费单价",
            "note": "大水磨暂无线头费配置",
            "unit_price": 0
        })
    
    # Step 4: 计算线头费
    thread_ends_cost = thread_ends_count * thread_ends_unit_price
    
    calculation_steps.append({
        "step": "计算线头费",
        "thread_ends_count": thread_ends_count,
        "unit_price": thread_ends_unit_price,
        "formula": f"{thread_ends_count} * {thread_ends_unit_price}",
        "thread_ends_cost": round(thread_ends_cost, 2)
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "part_type": part_type,
        "thread_ends_count": thread_ends_count,
        "thread_ends_cost": round(thread_ends_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "thread_ends_cost": thread_ends_cost,
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
        print("Usage: python price_water_mill_thread_ends.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
