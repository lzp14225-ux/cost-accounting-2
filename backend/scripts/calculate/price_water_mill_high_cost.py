"""
水磨高度费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（has_material_preparation, thickness_mm, quantity）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 如果 has_material_preparation 不为空，查询备料零件的厚度
5. 如果厚度不同，计算高度费：price
6. 更新 processing_cost_calculation_details 表的 high_cost
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
    "name": "calculate_water_mill_high_cost",
    "description": "计算水磨高度费：根据零件备料信息和厚度差异计算高度费用",
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
    计算水磨高度费
    
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
    
    logger.info(f"Calculating water mill high cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
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
                "value": d["high_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_high", "high_cost")
    
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
            "high": {
                "price": 4,
                "unit": "元/件"
            }
        }
    """
    price_map = {}
    
    # 处理小磨床价格
    for price in water_mill_data.get("s_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        
        if sub_category == "high":
            try:
                price_map["high"] = {
                    "price": float(price_value),
                    "unit": unit
                }
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse high price: {price_value}, error: {e}")
    
    return price_map


async def _get_material_preparation_thickness(job_id: str, part_code: str) -> float:
    """
    根据 part_code 查询备料零件的厚度
    
    Args:
        job_id: 任务ID
        part_code: 零件编号（如 B02）
    
    Returns:
        float: 备料零件的厚度，如果未找到返回 0
    """
    # Step 1: 根据 job_id 和 part_code 查询 subgraphs 表获取 subgraph_id
    sql_subgraph = """
        SELECT subgraph_id
        FROM subgraphs
        WHERE job_id = $1::uuid AND part_code = $2
        LIMIT 1
    """
    
    try:
        row = await db.fetch_one(sql_subgraph, job_id, part_code)
        if not row:
            logger.warning(f"No subgraph found for part_code: {part_code}")
            return 0
        
        subgraph_id = row["subgraph_id"]
        
        # Step 2: 根据 job_id 和 subgraph_id 查询 features 表获取 thickness_mm
        sql_features = """
            SELECT thickness_mm
            FROM features
            WHERE job_id = $1::uuid AND subgraph_id = $2
            LIMIT 1
        """
        
        row = await db.fetch_one(sql_features, job_id, subgraph_id)
        if not row:
            logger.warning(f"No features found for subgraph_id: {subgraph_id}")
            return 0
        
        thickness_mm = row["thickness_mm"] or 0
        logger.info(f"Found thickness {thickness_mm}mm for part_code: {part_code}")
        return float(thickness_mm)
        
    except Exception as e:
        logger.error(f"Failed to get material preparation thickness: {e}")
        return 0


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨高度费
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    has_auto_material = part.get("has_auto_material", False)
    has_material_preparation = part.get("has_material_preparation")
    thickness_mm = part.get("thickness_mm") or 0
    quantity = part.get("quantity") or 1
    
    logger.info(f"Calculating high cost for part: {part_name} ({subgraph_id})")
    
    # 判断水磨类型
    mill_type = determine_mill_type(has_auto_material, has_material_preparation)
    
    # 计算步骤
    calculation_steps = []
    
    # Step 1: 判断水磨类型
    calculation_steps.append({
        "step": "判断水磨类型",
        "has_auto_material": has_auto_material,
        "has_material_preparation": has_material_preparation,
        "mill_type": mill_type,
        "reason": f"has_auto_material={has_auto_material} 或 has_material_preparation={has_material_preparation}"
    })
    
    # Step 2: 只有小磨床才计算高度费
    if mill_type != "s_water_mill":
        calculation_steps.append({
            "step": "判断是否计算",
            "note": "高度费仅适用于小磨床，当前为大水磨，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "high_cost": 0,
            "note": "大水磨不计算高度费"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "high_cost": 0,
            "calculation_steps": calculation_steps
        }
    
    # Step 3: 检查是否有备料信息
    if not has_material_preparation:
        logger.info(f"No material preparation for {part_name}")
        calculation_steps.append({
            "step": "检查备料信息",
            "has_material_preparation": has_material_preparation,
            "note": "无备料信息，不计算高度费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "high_cost": 0,
            "note": "无备料信息"
        }, None
    
    calculation_steps.append({
        "step": "检查备料信息",
        "has_material_preparation": has_material_preparation,
        "note": f"备料于{has_material_preparation}"
    })
    
    # Step 3: 查询备料零件的厚度
    material_thickness = await _get_material_preparation_thickness(job_id, has_material_preparation)
    
    calculation_steps.append({
        "step": "查询备料零件厚度",
        "material_part_code": has_material_preparation,
        "material_thickness": material_thickness,
        "current_thickness": thickness_mm
    })
    
    # Step 4: 判断厚度是否不同
    if material_thickness == 0:
        calculation_steps.append({
            "step": "判断厚度差异",
            "note": f"未找到备料零件{has_material_preparation}的厚度信息，不计算高度费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "high_cost": 0,
            "note": f"未找到备料零件{has_material_preparation}的厚度"
        }, None
    
    if material_thickness == thickness_mm:
        calculation_steps.append({
            "step": "判断厚度差异",
            "material_thickness": material_thickness,
            "current_thickness": thickness_mm,
            "note": "厚度相同，不计算高度费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "material_thickness": material_thickness,
            "current_thickness": thickness_mm,
            "high_cost": 0,
            "note": "厚度相同"
        }, None
    
    calculation_steps.append({
        "step": "判断厚度差异",
        "material_thickness": material_thickness,
        "current_thickness": thickness_mm,
        "thickness_diff": abs(material_thickness - thickness_mm),
        "note": "厚度不同，需计算高度费"
    })
    
    # Step 5: 获取高度费单价
    high_info = price_map.get("high", {})
    high_unit_price = high_info.get("price", 0)
    unit = high_info.get("unit", "")
    
    calculation_steps.append({
        "step": "获取高度费单价",
        "unit_price": high_unit_price,
        "unit": unit
    })
    
    # Step 6: 计算高度费（单件，不乘数量）
    high_cost = high_unit_price
    
    calculation_steps.append({
        "step": "计算高度费",
        "quantity": quantity,
        "unit_price": high_unit_price,
        "formula": f"{high_unit_price}",
        "high_cost": round(high_cost, 2)
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "material_part_code": has_material_preparation,
        "material_thickness": material_thickness,
        "current_thickness": thickness_mm,
        "quantity": quantity,
        "high_cost": round(high_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "high_cost": high_cost,
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
        print("Usage: python price_water_mill_high_cost.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
