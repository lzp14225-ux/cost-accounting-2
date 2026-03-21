"""
水磨倒角费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（water_mill, has_auto_material, has_material_preparation）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 计算倒角费：c1_c2 + c3_c5 + r1_r2 + r3_r5
5. 更新 processing_cost_calculation_details 表的 chamfer_cost
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
    "name": "calculate_water_mill_chamfer_cost",
    "description": "计算水磨倒角费：根据零件water_mill数据和价格配置计算倒角费用",
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
    计算水磨倒角费
    
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
    
    logger.info(f"Calculating water mill chamfer cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
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
                "value": d["chamfer_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_chamfer", "chamfer_cost")
    
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
            "c1_c2_chamfer": {"price": 3, "unit": "个/min"},
            "c3_c5_chamfer": {"price": 5, "unit": "个/min"},
            "r1_r2_chamfer": {"price": 8, "unit": "个/min"},
            "r3_r5_chamfer": {"price": 10, "unit": "个/min"}
        }
    """
    price_map = {}
    
    chamfer_types = ["c1_c2_chamfer", "c3_c5_chamfer", "r1_r2_chamfer", "r3_r5_chamfer"]
    
    # 处理小磨床价格
    for price in water_mill_data.get("s_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        
        if sub_category in chamfer_types:
            try:
                price_map[sub_category] = {
                    "price": float(price_value),
                    "unit": unit
                }
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse {sub_category} price: {price_value}, error: {e}")
    
    return price_map


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨倒角费
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    has_auto_material = part.get("has_auto_material", False)
    has_material_preparation = part.get("has_material_preparation")
    water_mill = part.get("water_mill")
    
    logger.info(f"Calculating chamfer cost for part: {part_name} ({subgraph_id})")
    
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
            "chamfer_cost": 0,
            "note": "无water_mill_details数据"
        }, None
    
    water_mill_details = water_mill["water_mill_details"]
    
    # 获取各类倒角数量
    chamfer_counts = {
        "c1_c2_chamfer": 0,
        "c3_c5_chamfer": 0,
        "r1_r2_chamfer": 0,
        "r3_r5_chamfer": 0
    }
    
    for detail in water_mill_details:
        for chamfer_type in chamfer_counts.keys():
            if chamfer_type in detail:
                chamfer_counts[chamfer_type] = detail.get(chamfer_type, 0)
    
    # Step 1: 判断水磨类型
    calculation_steps.append({
        "step": "判断水磨类型",
        "has_auto_material": has_auto_material,
        "has_material_preparation": has_material_preparation,
        "mill_type": mill_type,
        "reason": f"has_auto_material={has_auto_material} 或 has_material_preparation={has_material_preparation}"
    })
    
    # Step 2: 只有小磨床才计算倒角费
    if mill_type != "s_water_mill":
        calculation_steps.append({
            "step": "判断是否计算",
            "note": "倒角费仅适用于小磨床，当前为大水磨，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "chamfer_cost": 0,
            "note": "大水磨不计算倒角费"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "chamfer_cost": 0,
            "calculation_steps": calculation_steps
        }
    
    # Step 3: 计算各类倒角费用
    chamfer_costs = {}
    total_chamfer_cost = 0
    
    for chamfer_type, count in chamfer_counts.items():
        if count == 0:
            continue
        
        price_info = price_map.get(chamfer_type, {})
        unit_price = price_info.get("price", 0)
        unit = price_info.get("unit", "")
        
        cost = count * unit_price
        chamfer_costs[chamfer_type] = cost
        total_chamfer_cost += cost
        
        calculation_steps.append({
            "step": f"计算{chamfer_type}费用",
            "chamfer_type": chamfer_type,
            "count": count,
            "unit_price": unit_price,
            "unit": unit,
            "formula": f"{count} * {unit_price}",
            "cost": round(cost, 2)
        })
    
    # Step 3: 汇总倒角费用
    if chamfer_costs:
        formula_parts = [f"{k}({round(v, 2)})" for k, v in chamfer_costs.items()]
        calculation_steps.append({
            "step": "汇总倒角费用",
            "formula": " + ".join(formula_parts) + f" = {round(total_chamfer_cost, 2)}",
            "chamfer_costs": {k: round(v, 2) for k, v in chamfer_costs.items()},
            "total_chamfer_cost": round(total_chamfer_cost, 2)
        })
    else:
        calculation_steps.append({
            "step": "汇总倒角费用",
            "note": "所有倒角数量均为0",
            "total_chamfer_cost": 0
        })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "chamfer_counts": chamfer_counts,
        "chamfer_costs": {k: round(v, 2) for k, v in chamfer_costs.items()},
        "chamfer_cost": round(total_chamfer_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "chamfer_cost": total_chamfer_cost,
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
        print("Usage: python price_water_mill_chamfer_cost.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
