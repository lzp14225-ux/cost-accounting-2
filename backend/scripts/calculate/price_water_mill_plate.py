"""
水磨板费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（尺寸, material, needs_heat_treatment, has_auto_material, has_material_preparation）
2. 调用 water_mill_search 获取水磨价格信息
3. 判断是大水磨还是小磨床
4. 只有大水磨且为板时才进行计算
5. 根据是否需要热处理和材料类型确定单价
6. 计算板费：金额 = 长 × 宽 ÷ 1290 × 单价
7. 更新 processing_cost_calculation_details 表的 plate_cost
"""
from typing import List, Dict, Any
import logging
import asyncio

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps
from ._water_mill_helper import determine_mill_type, determine_part_type

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_water_mill_plate_price",
    "description": "计算水磨板费：根据零件尺寸、热处理需求和材料类型计算板费用",
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
    计算水磨板费
    
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
    
    logger.info(f"Calculating water mill plate cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
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
                "value": d["plate_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "water_mill_plate", "plate_cost")
    
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
            "plate_no_heat": 0.15,           # 不需要热处理的单价
            "plate_heat_45": 0.17,           # 需要热处理且材料为45#的单价
            "plate_heat_other": 0.2,         # 需要热处理且材料为其他的单价
            "min_area": 1290                 # 除数（mm²）
        }
    """
    price_map = {
        "plate_no_heat": 0,
        "plate_heat_45": 0,
        "plate_heat_other": 0,
        "min_area": 0
    }
    
    # 处理大水磨价格
    for price in water_mill_data.get("l_water_mill_prices", []):
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        unit = price.get("unit")
        min_num = str(price.get("min_num") or "").strip()
        
        if sub_category == "plate":
            try:
                price_float = float(price_value)
                
                # 根据 unit + min_num 判断价格类型
                if unit == "元/mm2":
                    if min_num == "非热处理":
                        price_map["plate_no_heat"] = price_float
                    elif min_num == "45#调质/HRC":
                        price_map["plate_heat_45"] = price_float
                    elif min_num == "热处理单价":
                        price_map["plate_heat_other"] = price_float
                    else:
                        logger.warning(
                            f"Unknown plate pricing rule for min_num='{min_num}', price={price_value}"
                        )
                elif unit == "mm2":
                    # 这是除数，用于计算公式：金额 = 长 × 宽 ÷ min_area × 单价
                    price_map["min_area"] = price_float
                    
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse plate price: {price_value}, error: {e}")
    return price_map


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的水磨板费

    说明：
    - 该脚本只计算单件板费金额（plate_cost）
    - quantity 不在此脚本中参与计算，统一由 price_water_mill_total.py 做总价/总时间汇总
    - 板费对应的加工时间也统一由 price_water_mill_total.py 按大水磨时薪换算
    
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
    needs_heat_treatment = part.get("needs_heat_treatment", False)
    material = part.get("material", "")
    
    logger.info(f"Calculating plate cost for part: {part_name} ({subgraph_id})")
    
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
    
    # Step 2: 只有大水磨才计算板费
    if mill_type != "l_water_mill":
        calculation_steps.append({
            "step": "判断是否计算",
            "note": "板费仅适用于大水磨，当前为小磨床，返回0"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "plate_cost": 0,
            "note": "小磨床不计算板费"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "plate_cost": 0,
            "calculation_steps": calculation_steps
        }
    
    # Step 3: 检查尺寸是否有效
    if length_mm == 0 or width_mm == 0:
        calculation_steps.append({
            "step": "检查尺寸",
            "length_mm": length_mm,
            "width_mm": width_mm,
            "note": "长或宽为0，无法计算板费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "plate_cost": 0,
            "note": "长或宽为0"
        }, None
    
    # Step 4: 判断零件类型
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
    
    # Step 5: 只有板才计算板费
    if part_type != "plate":
        calculation_steps.append({
            "step": "判断是否为板",
            "part_type": part_type,
            "note": "当前零件不是板，不计算板费"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "mill_type": mill_type,
            "part_type": part_type,
            "plate_cost": 0,
            "note": "不是板类型"
        }, None
    
    # Step 6: 根据热处理需求和材料确定单价
    unit_price = 0
    price_type = ""
    
    if needs_heat_treatment:
        # 需要热处理
        if material == "45#":
            unit_price = price_map["plate_heat_45"]
            price_type = "需要热处理且材料为45#"
        else:
            unit_price = price_map["plate_heat_other"]
            price_type = f"需要热处理且材料为{material}"
    else:
        # 不需要热处理
        unit_price = price_map["plate_no_heat"]
        price_type = "不需要热处理"
    
    calculation_steps.append({
        "step": "确定单价",
        "needs_heat_treatment": needs_heat_treatment,
        "material": material,
        "unit_price": unit_price,
        "price_type": price_type
    })
    
    # Step 7: 计算面积
    area = length_mm * width_mm
    min_area = price_map["min_area"]
    
    calculation_steps.append({
        "step": "计算面积",
        "length_mm": length_mm,
        "width_mm": width_mm,
        "area": area,
        "divisor": min_area,
        "note": f"面积 = {length_mm} * {width_mm} = {area}mm²，除数 = {min_area}mm²"
    })
    
    # Step 8: 计算单件板费金额
    # 确保所有值都是 float 类型，避免 Decimal 和 float 混合运算
    area = float(area)
    min_area = float(min_area)
    unit_price = float(unit_price)
    
    # 计算公式：金额 = 长 × 宽 ÷ 1290 × 单价
    if min_area > 0:
        plate_cost = (area / min_area) * unit_price
        calculation_steps.append({
            "step": "计算板费",
            "length_mm": length_mm,
            "width_mm": width_mm,
            "area": area,
            "divisor": min_area,
            "unit_price": unit_price,
            "formula": f"({length_mm} * {width_mm}) / {min_area} * {unit_price}",
            "calculation": f"{area} / {min_area} * {unit_price} = {round(plate_cost, 2)}",
            "plate_cost": round(plate_cost, 2)
        })
    else:
        # 如果 min_area 为 0，避免除零错误
        plate_cost = 0
        calculation_steps.append({
            "step": "计算板费",
            "area": area,
            "divisor": min_area,
            "unit_price": unit_price,
            "plate_cost": 0,
            "note": "除数为0，无法计算板费"
        })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "mill_type": mill_type,
        "part_type": part_type,
        "needs_heat_treatment": needs_heat_treatment,
        "material": material,
        "area": area,
        "unit_price": unit_price,
        "plate_cost": round(plate_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "plate_cost": plate_cost,
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
        print("Usage: python price_water_mill_plate.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用 search 脚本获取数据
    print("请先调用 base_itemcode_search 和 water_mill_search 获取数据")
    print("然后将数据传入 calculate() 函数")
