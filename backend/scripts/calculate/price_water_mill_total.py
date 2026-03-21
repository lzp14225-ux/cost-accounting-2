"""
水磨总价计算脚本
负责人：李志鹏

计算流程：
1. 从 base_itemcode_search.py 获取零件基础信息（包含 quantity、has_auto_material、has_material_preparation）
2. 从 total_search.py 获取成本明细（包含各项水磨费用）
3. 从 water_mill_search.py 获取水磨价格信息（50元/小时、60元/小时）
4. 判断大小磨床：
   - 小磨床：计算 small_grinding_cost = (chamfer_cost+bevel_cost+oil_tank_cost)*quantity*50 + (thread_ends_cost+hanging_table_cost+high_cost)*quantity
              计算 small_grinding_time = (chamfer_cost+bevel_cost+oil_tank_cost)*quantity（小时）
   - 大水磨：计算 large_grinding_cost = (long_strip_cost+component_cost)*quantity*60 + plate_cost*quantity
              计算 large_grinding_time = (long_strip_cost+component_cost)*quantity（小时）
5. 批量更新 subgraphs 表（费用和时间）
"""
from typing import List, Dict, Any
from decimal import Decimal, ROUND_HALF_UP
import logging
import asyncio
import json

from api_gateway.database import db
from ._water_mill_helper import determine_mill_type
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_water_mill_total_cost",
    "description": "计算水磨总价和时间：根据大小磨床类型计算总费用和加工时间，更新到 subgraphs 表",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode、total 和 water_mill"
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
    "needs": ["base_itemcode", "total", "water_mill"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算水磨总价并更新 subgraphs 表
    
    Args:
        search_data: 检索数据，包含 base_itemcode、total 和 water_mill
        job_id: 任务ID（可选）
        subgraph_ids: 子图ID列表（可选）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    total_data = search_data["total"]
    water_mill_data = search_data["water_mill"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating water mill total cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # 构建价格映射
    price_map = _build_price_map(water_mill_data)
    
    # 构建映射
    # 1. cost_map: subgraph_id -> cost_details
    cost_map = {
        detail["subgraph_id"]: detail
        for detail in total_data["cost_details"]
    }
    
    # 计算各项总价
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_total(
            part, cost_map, price_map
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # 批量更新 processing_cost_calculation_details 表（更新 calculation_steps）
    if db_updates:
        # 分别更新小磨床和大水磨的 calculation_steps
        small_grinding_updates = []
        large_grinding_updates = []
        
        for d in db_updates:
            if d.get("mill_type") == "s_water_mill" and d.get("small_grinding_cost", 0) > 0:
                small_grinding_updates.append({
                    "job_id": job_id,
                    "subgraph_id": d["subgraph_id"],
                    "value": d["small_grinding_cost"],
                    "steps": d.get("calculation_steps", [])
                })
            elif d.get("mill_type") == "l_water_mill" and d.get("large_grinding_cost", 0) > 0:
                large_grinding_updates.append({
                    "job_id": job_id,
                    "subgraph_id": d["subgraph_id"],
                    "value": d["large_grinding_cost"],
                    "steps": d.get("calculation_steps", [])
                })
        
        # 更新小磨床
        if small_grinding_updates:
            await batch_upsert_with_steps(small_grinding_updates, "water_mill_total_small", None)
        
        # 更新大水磨
        if large_grinding_updates:
            await batch_upsert_with_steps(large_grinding_updates, "water_mill_total_large", None)
    
    # 批量更新 subgraphs 表
    if db_updates:
        await _batch_update_subgraphs(job_id, db_updates)
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(water_mill_data: Dict[str, Any]) -> Dict[str, float]:
    """
    构建价格映射
    
    Returns:
        {
            "small_hourly_rate": 50,  # 小磨床时薪（元/小时）
            "large_hourly_rate": 60   # 大水磨时薪（元/小时）
        }
    """
    price_map = {
        "small_hourly_rate": 0,
        "large_hourly_rate": 0
    }
    
    logger.info(f"Building price map from water_mill_data keys: {water_mill_data.keys()}")
    
    # 处理小磨床价格（从 s_water_mill_prices 中查找）
    for price in water_mill_data.get("s_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        
        if sub_category == "water_mill" and unit == "元/小时":
            try:
                price_float = float(price_value)
                price_map["small_hourly_rate"] = price_float
                logger.info(f"Set small_hourly_rate to {price_float} from s_water_mill_prices")
                break
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse small water_mill price: {price_value}, error: {e}")
    
    # 处理大水磨价格（从 l_water_mill_prices 中查找）
    for price in water_mill_data.get("l_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        
        if sub_category == "water_mill" and unit == "元/小时":
            try:
                price_float = float(price_value)
                price_map["large_hourly_rate"] = price_float
                logger.info(f"Set large_hourly_rate to {price_float} from l_water_mill_prices")
                break
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse large water_mill price: {price_value}, error: {e}")
    
    logger.info(f"Final price_map: {price_map}")
    return price_map


async def _calculate_part_total(
    part: Dict,
    cost_map: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨总价和时间
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    quantity = part.get("quantity", 1)
    has_auto_material = part.get("has_auto_material", False)
    has_material_preparation = part.get("has_material_preparation")
    costs = cost_map.get(subgraph_id, {})
    
    logger.info(f"Calculating water mill total for part: {part_name} ({subgraph_id}), quantity: {quantity}")
    
    # 判断水磨类型
    mill_type = determine_mill_type(has_auto_material, has_material_preparation)
    
    # 初始化结果
    small_grinding_cost = 0.0
    large_grinding_cost = 0.0
    small_grinding_time = 0.0
    large_grinding_time = 0.0
    calculation_steps = []
    
    # 添加判断水磨类型的步骤
    calculation_steps.append({
        "step": "判断水磨类型",
        "has_auto_material": has_auto_material,
        "has_material_preparation": has_material_preparation,
        "mill_type": mill_type,
        "description": "小磨床" if mill_type == "s_water_mill" else "大水磨"
    })
    
    if mill_type == "s_water_mill":
        # 小磨床计算
        small_grinding_cost, small_grinding_time, small_steps = _calculate_small_grinding_cost(
            costs, quantity, price_map["small_hourly_rate"]
        )
        calculation_steps.extend(small_steps)
    elif mill_type == "l_water_mill":
        # 大水磨计算
        large_grinding_cost, large_grinding_time, large_steps = _calculate_large_grinding_cost(
            costs, quantity, price_map["large_hourly_rate"]
        )
        calculation_steps.extend(large_steps)
    
    # 构建结果
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "quantity": quantity,
        "mill_type": mill_type,
        "small_grinding_cost": small_grinding_cost,
        "large_grinding_cost": large_grinding_cost,
        "small_grinding_time": small_grinding_time,
        "large_grinding_time": large_grinding_time
    }
    
    db_data = {
        "subgraph_id": subgraph_id,
        "mill_type": mill_type,
        "small_grinding_cost": small_grinding_cost,
        "large_grinding_cost": large_grinding_cost,
        "small_grinding_time": small_grinding_time,
        "large_grinding_time": large_grinding_time,
        "calculation_steps": calculation_steps
    }
    
    logger.info(
        f"[{subgraph_id}] {part_name}: mill_type={mill_type}, quantity={quantity}, "
        f"small_grinding_cost={small_grinding_cost:.2f}, large_grinding_cost={large_grinding_cost:.2f}, "
        f"small_grinding_time={small_grinding_time:.2f}h, large_grinding_time={large_grinding_time:.2f}h"
    )
    
    return result, db_data


def _calculate_small_grinding_cost(costs: Dict, quantity: int, hourly_rate: float) -> tuple[float, float, List[Dict]]:
    """
    计算小磨床费用和时间

    公式：(chamfer_cost+bevel_cost+oil_tank_cost)*quantity*50 + (thread_ends_cost+hanging_table_cost+high_cost)*quantity

    单位说明：
    - thread_ends_cost: 元（单件）
    - hanging_table_cost: 元（单件）
    - high_cost: 元（单件）
    - chamfer_cost: 分钟 -> 需要转换为小时
    - bevel_cost: 分钟 -> 需要转换为小时
    - oil_tank_cost: 小时

    Returns:
        tuple: (cost, time_hours, calculation_steps) - (费用, 时间（小时）, 计算步骤)
    """

    calculation_steps = []
    
    # 获取各项费用
    thread_ends_cost = costs.get("thread_ends_cost", 0.0)
    hanging_table_cost = costs.get("hanging_table_cost", 0.0)
    high_cost = costs.get("high_cost", 0.0)
    chamfer_cost = costs.get("chamfer_cost", 0.0)  # 分钟
    bevel_cost = costs.get("bevel_cost", 0.0)  # 分钟
    oil_tank_cost = costs.get("oil_tank_cost", 0.0)  # 小时
    
    calculation_steps.append({
        "step": "获取小磨床各项费用",
        "thread_ends_cost": thread_ends_cost,
        "hanging_table_cost": hanging_table_cost,
        "high_cost": high_cost,
        "chamfer_cost_minutes": chamfer_cost,
        "bevel_cost_minutes": bevel_cost,
        "oil_tank_cost_hours": oil_tank_cost
    })
    
    # 将分钟转换为小时
    chamfer_cost_hours = chamfer_cost / 60.0
    bevel_cost_hours = bevel_cost / 60.0
    
    calculation_steps.append({
        "step": "转换时间单位",
        "chamfer_cost_hours": round(chamfer_cost_hours, 4),
        "bevel_cost_hours": round(bevel_cost_hours, 4),
        "note": "分钟转换为小时"
    })
    
    # 计算时间费用部分：(chamfer_cost+bevel_cost+oil_tank_cost) * quantity * hourly_rate
    time_cost_hours = chamfer_cost_hours + bevel_cost_hours + oil_tank_cost
    time_cost_total = time_cost_hours * quantity * hourly_rate
    
    calculation_steps.append({
        "step": "计算时间费用",
        "formula": f"({round(chamfer_cost_hours, 4)} + {round(bevel_cost_hours, 4)} + {oil_tank_cost}) × {quantity} × {hourly_rate}",
        "time_cost_hours": round(time_cost_hours, 4),
        "quantity": quantity,
        "hourly_rate": hourly_rate,
        "time_cost_total": round(time_cost_total, 2)
    })
    
    # 计算固定费用部分：(thread_ends_cost + hanging_table_cost + high_cost) * quantity
    fixed_cost_total = (thread_ends_cost + hanging_table_cost + high_cost) * quantity

    
    calculation_steps.append({
    "step": "计算固定费用",
    "formula": f"({thread_ends_cost} + {hanging_table_cost} + {high_cost}) × {quantity}",
    "thread_ends_cost": thread_ends_cost,
    "hanging_table_cost": hanging_table_cost,
    "high_cost": high_cost,
    "quantity": quantity,
    "fixed_cost_total": round(fixed_cost_total, 2)
    })

    
    # 总费用
    total_cost = time_cost_total + fixed_cost_total
    
    # 总时间（小时）= 单件时间 * 数量
    total_time_hours = time_cost_hours * quantity
    
    calculation_steps.append({
        "step": "计算小磨床总费用和总时间",
        "formula": f"{round(time_cost_total, 2)} + {round(fixed_cost_total, 2)}",
        "total_cost": round(total_cost, 2),
        "total_time_hours": round(total_time_hours, 2)
    })
    
    logger.info(
        f"Small grinding: chamfer={chamfer_cost}min, bevel={bevel_cost}min, oil_tank={oil_tank_cost}h, "
        f"time_hours={time_cost_hours:.2f}h, time_cost={time_cost_total:.2f}, "
        f"fixed_cost={fixed_cost_total:.2f}, total={total_cost:.2f}, total_time={total_time_hours:.2f}h"
    )
    
    cost_rounded = float(Decimal(str(total_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    time_rounded = float(Decimal(str(total_time_hours)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    
    return cost_rounded, time_rounded, calculation_steps


def _calculate_large_grinding_cost(costs: Dict, quantity: int, hourly_rate: float) -> tuple[float, float, List[Dict]]:
    """
    计算大水磨费用和时间
    
    公式：(long_strip_cost+component_cost)*quantity*60 + plate_cost*quantity
    
    单位说明：
    - long_strip_cost: 小时
    - component_cost: 小时
    - plate_cost: 元
    
    Returns:
        tuple: (cost, time_hours, calculation_steps) - (费用, 时间（小时）, 计算步骤)
    """
    calculation_steps = []
    
    # 获取各项费用
    plate_cost = costs.get("plate_cost", 0.0)  # 元
    long_strip_cost = costs.get("long_strip_cost", 0.0)  # 小时
    component_cost = costs.get("component_cost", 0.0)  # 小时
    
    calculation_steps.append({
        "step": "获取大水磨各项费用",
        "plate_cost": plate_cost,
        "long_strip_cost_hours": long_strip_cost,
        "component_cost_hours": component_cost
    })
    
    # 计算时间费用部分：(long_strip_cost + component_cost) * quantity * hourly_rate
    time_cost_hours = long_strip_cost + component_cost
    time_cost_total = time_cost_hours * quantity * hourly_rate
    
    calculation_steps.append({
        "step": "计算时间费用",
        "formula": f"({long_strip_cost} + {component_cost}) × {quantity} × {hourly_rate}",
        "time_cost_hours": round(time_cost_hours, 4),
        "quantity": quantity,
        "hourly_rate": hourly_rate,
        "time_cost_total": round(time_cost_total, 2)
    })
    
    # 计算板费部分：plate_cost * quantity
    plate_cost_total = plate_cost * quantity
    
    calculation_steps.append({
        "step": "计算板费",
        "formula": f"{plate_cost} × {quantity}",
        "plate_cost_total": round(plate_cost_total, 2)
    })
    
    # 总费用
    total_cost = time_cost_total + plate_cost_total
    
    # 总时间（小时）= 单件时间 * 数量
    total_time_hours = time_cost_hours * quantity
    
    calculation_steps.append({
        "step": "计算大水磨总费用和总时间",
        "formula": f"{round(time_cost_total, 2)} + {round(plate_cost_total, 2)}",
        "total_cost": round(total_cost, 2),
        "total_time_hours": round(total_time_hours, 2)
    })
    
    logger.info(
        f"Large grinding: long_strip={long_strip_cost}h, component={component_cost}h, "
        f"time_hours={time_cost_hours:.2f}h, time_cost={time_cost_total:.2f}, "
        f"plate_cost={plate_cost_total:.2f}, total={total_cost:.2f}, total_time={total_time_hours:.2f}h"
    )
    
    cost_rounded = float(Decimal(str(total_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    time_rounded = float(Decimal(str(total_time_hours)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    
    return cost_rounded, time_rounded, calculation_steps


async def _batch_update_subgraphs(job_id: str, updates: List[Dict]):
    """
    批量更新 subgraphs 表
    
    Args:
        job_id: 任务ID
        updates: 更新数据列表
    """
    logger.info(f"Batch updating {len(updates)} records to subgraphs table")
    
    # 构建批量更新 SQL
    sql = """
        UPDATE subgraphs
        SET 
            small_grinding_cost = $3,
            large_grinding_cost = $4,
            small_grinding_time = $5,
            large_grinding_time = $6,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    try:
        # 并发执行所有更新
        tasks = []
        for data in updates:
            tasks.append(db.execute(
                sql,
                job_id,
                data["subgraph_id"],
                data["small_grinding_cost"],
                data["large_grinding_cost"],
                data["small_grinding_time"],
                data["large_grinding_time"]
            ))
        
        await asyncio.gather(*tasks)
        logger.info(f"Successfully updated {len(updates)} records")
    
    except Exception as e:
        logger.error(f"Failed to batch update subgraphs: {e}")
        raise


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
    
    print("price_water_mill_total.py - 水磨总价计算脚本")
    print("需要配合 base_itemcode_search.py、total_search.py 和 water_mill_search.py 使用")
    print("\n使用方式：")
    print("1. 先执行 base_itemcode_search.py 获取零件信息")
    print("2. 再执行 total_search.py 获取成本明细")
    print("3. 再执行 water_mill_search.py 获取水磨价格")
    print("4. 最后调用本脚本计算总价并更新 subgraphs 表")
