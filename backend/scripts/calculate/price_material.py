"""
材料费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（material, length_mm, width_mm, thickness_mm）
2. 调用 material_search 获取材料价格信息
3. 调用 density_search 获取材料密度数据
4. 根据 material 匹配 sub_category 获取单价（不区分大小写，支持材质别名映射）
5. 根据 material 匹配密度值（不区分大小写，支持材质别名映射）
6. 根据备料形状计算体积：方料 length*width*thickness；圆料 PI*(diameter/2)^2*thickness
7. 计算重量：weight = density * stock_volume_mm3
8. 计算材料费：material_cost = weight * price
9. 更新 processing_cost_calculation_details 表的 material_cost 字段和步骤字段

材质别名映射（价格表中存储的是 T00L0X33 和 T00L0X44）：
- TOOLOX33 -> T00L0X33
- TOOLOX44 -> T00L0X44
"""
from typing import List, Dict, Any
from decimal import Decimal, ROUND_HALF_UP
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps
from .material_shape_helper import (
    get_material_shape,
    get_shape_price_category,
    get_stock_volume_mm3,
)

logger = logging.getLogger(__name__)

# 材质别名映射（用于材质适配）
# 价格表中存储的是 T00L0X33 和 T00L0X44，需要将别名转换为价格表中的标准名称
MATERIAL_ALIASES = {
    "TOOLOX33": "T00L0X33",
    "TOOLOX44": "T00L0X44",
}

# 默认密度（钢材，当找不到匹配材料时使用）
DEFAULT_DENSITY = Decimal("0.00000785")

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_material_cost",
    "description": "计算材料费：根据零件信息、材料价格和密度计算费用",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode、material 和 density"
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
    "needs": ["base_itemcode", "material", "density"]
}

def _build_density_map(density_data: List[Dict]) -> Dict[str, Decimal]:
    """
    构建材料密度映射表（不区分大小写）
    
    Returns:
        Dict[str, Decimal]: {材料名称(大写): 密度值}
    """
    density_map = {}
    for item in density_data:
        material = item.get("sub_category", "").upper()
        density = Decimal(str(item.get("price", 0)))
        density_map[material] = density
    
    logger.info(f"Built density map with {len(density_map)} materials")
    return density_map


def _get_material_density(material: str, density_map: Dict[str, Decimal]) -> tuple[Decimal, str]:
    """
    获取材料密度（支持别名映射，不区分大小写）
    
    Returns:
        (density, matched_material_name)
    """
    if not material:
        logger.warning("Material is empty, using default density")
        return DEFAULT_DENSITY, "默认钢材"
    
    # 转换为大写
    material_upper = material.upper()
    
    # 检查是否有别名映射
    if material_upper in MATERIAL_ALIASES:
        mapped_material = MATERIAL_ALIASES[material_upper]
        logger.info(f"Material alias mapping: {material} -> {mapped_material}")
        material_upper = mapped_material
    
    # 查找密度
    if material_upper in density_map:
        density = density_map[material_upper]
        logger.info(f"Found density for material {material}: {density}")
        return density, material_upper
    
    # 未找到，使用默认值
    logger.warning(f"Material {material} not found in density map, using default density")
    return DEFAULT_DENSITY, f"{material}(使用默认密度)"


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算材料费
    
    Args:
        search_data: 检索数据，包含 base_itemcode、material 和 density
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    material_data = search_data["material"]
    density_data = search_data["density"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating material cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 1: 构建密度映射表
    density_map = _build_density_map(density_data.get("density_data", []))
    
    # Step 2: 构建价格映射 (sub_category 转大写作为 key -> {price, unit})
    price_map = {}
    for price_item in material_data.get("material_prices", []):
        category = price_item.get("category", "material")
        sub_category = price_item.get("sub_category")
        if category not in price_map:
            price_map[category] = {}
        # 转大写作为 key，实现不区分大小写匹配
        price_map[category][sub_category.upper()] = {
            "price": float(price_item.get("price", 0)),
            "unit": price_item.get("unit", ""),
            "original_sub_category": sub_category  # 保留原始值用于显示
        }
    
    # Step 3: 计算每个零件的材料费（不写数据库）
    results = []
    db_updates = []  # 收集需要写入数据库的数据
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_cost(
            job_id, part, price_map, density_map
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
                "value": d["material_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "material", "material_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _calculate_part_cost(
    job_id: str,
    part: Dict,
    price_map: Dict,
    density_map: Dict[str, Decimal]
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的材料费
    
    Returns:
        tuple: (result_dict, db_update_dict)
            - result_dict: 返回给调用方的结果
            - db_update_dict: 需要写入数据库的数据（如果有错误则为None）
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    material = part.get("material")  # 例如: 45#
    length_mm = part.get("length_mm")
    width_mm = part.get("width_mm")
    thickness_mm = part.get("thickness_mm")
    
    logger.info(f"Calculating cost for part: {part_name} ({subgraph_id}), material: {material}")
    
    # 检查必需字段
    if not all([length_mm, width_mm, thickness_mm]):
        missing = []
        if not length_mm:
            missing.append("length_mm")
        if not width_mm:
            missing.append("width_mm")
        if not thickness_mm:
            missing.append("thickness_mm")
        
        logger.warning(f"Missing required fields for {part_name}: {', '.join(missing)}, skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "数据验证",
            "status": "failed",
            "reason": f"缺少必需字段: {', '.join(missing)}",
            "missing_fields": missing,
            "material_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "material_cost": 0.0,
            "note": f"缺少必需字段: {', '.join(missing)}"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "material_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    # 根据 material 匹配 sub_category（不区分大小写）
    if not material:
        logger.warning(f"material is empty for part: {part_name}, skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "数据验证",
            "status": "failed",
            "reason": "material为空",
            "material_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "material_cost": 0.0,
            "note": "material为空"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "material_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    # 材质适配：先转大写，然后检查是否有别名映射
    material_upper = material.upper()
    original_material = material
    
    # 如果材质在别名映射中，使用映射后的材质
    if material_upper in MATERIAL_ALIASES:
        material_mapped = MATERIAL_ALIASES[material_upper]
        logger.info(f"Material alias mapping: {material} -> {material_mapped}")
    else:
        material_mapped = material_upper
    
    # 获取对应的价格信息（使用映射后的材质进行匹配）
    material_shape = get_material_shape(part)
    price_category = get_shape_price_category(part, "material", "r_material")
    price_info = price_map.get(price_category, {}).get(material_mapped)
    if not price_info:
        logger.warning(f"No price found for material: {material} (mapped to: {material_mapped}), skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "匹配材料价格",
            "status": "failed",
            "material": material,
            "mapped_material": material_mapped,
            "reason": f"未找到material对应的价格: {material}",
            "material_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "material": material,
            "material_cost": 0.0,
            "note": f"未找到material对应的价格: {material}"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "material_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    unit_price = price_info["price"]
    unit = price_info["unit"]
    matched_sub_category = price_info.get("original_sub_category", material_mapped)
    
    # 获取材料密度
    density, matched_density_material = _get_material_density(material, density_map)
    
    # 转换为 Decimal 进行精确计算
    length = Decimal(str(length_mm))
    width = Decimal(str(width_mm))
    thickness = Decimal(str(thickness_mm))
    
    # 计算重量：先按备料形状计算体积，再乘材料密度
    volume_mm3 = get_stock_volume_mm3(part)
    weight = (density * volume_mm3).quantize(
        Decimal("0.0001"), ROUND_HALF_UP
    )
    
    # 计算材料费: material_cost = weight * price
    material_cost = (weight * Decimal(str(unit_price))).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    
    # 构建计算步骤
    calculation_steps = [
        {
            "step": "匹配材料价格",
            "material_shape": material_shape,
            "price_category": price_category,
            "material": original_material,
            "matched_sub_category": matched_sub_category,
            "match_note": f"不区分大小写匹配: {original_material} -> {matched_sub_category}" + (f" (别名映射: {material_upper} -> {material_mapped})" if material_upper in MATERIAL_ALIASES else ""),
            "unit_price": unit_price,
            "unit": unit
        },
        {
            "step": "匹配材料密度",
            "material": original_material,
            "matched_material": matched_density_material,
            "density": float(density),
            "unit": "kg/mm³"
        },
        {
            "step": "获取尺寸数据",
            "length_mm": float(length_mm),
            "width_mm": float(width_mm),
            "thickness_mm": float(thickness_mm)
        },
        {
            "step": "计算重量",
            "formula": f"{density} * volume_mm3({volume_mm3})",
            "volume_mm3": float(volume_mm3),
            "weight": float(weight)
        },
        {
            "step": "计算材料费",
            "formula": f"{float(weight)} * {unit_price}",
            "material_cost": float(material_cost)
        }
    ]
    
    logger.info(
        f"[{subgraph_id}] {part_name}: material={original_material}, weight={weight}, "
        f"unit_price={unit_price}, material_cost={material_cost}"
    )
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "material": original_material,
        "length_mm": float(length_mm),
        "width_mm": float(width_mm),
        "thickness_mm": float(thickness_mm),
        "weight": float(weight),
        "unit_price": unit_price,
        "unit": unit,
        "material_cost": float(material_cost)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "material_cost": float(material_cost),
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _update_calculation_details(
    job_id: str,
    subgraph_id: str,
    material_cost: float,
    new_steps: List[Dict]
):
    """
    更新 processing_cost_calculation_details 表（保留用于向后兼容）
    如果已存在 material 字段则覆盖，否则追加
    """
    # 使用批量更新助手
    await batch_upsert_with_steps(
        [{
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "value": material_cost,
            "steps": new_steps
        }],
        "material",
        "material_cost"
    )


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
        print("Usage: python price_material.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
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
            print(f"  材料: {result['material']}")
            print(f"  尺寸: {result['length_mm']} x {result['width_mm']} x {result['thickness_mm']} mm")
            print(f"  重量: {result['weight']} kg")
            print(f"  单价: {result['unit_price']} {result['unit']}")
            print(f"  材料费: {result['material_cost']} 元")

