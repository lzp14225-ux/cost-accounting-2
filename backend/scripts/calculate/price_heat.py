"""
热处理费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（needs_heat_treatment, material, length_mm, width_mm, thickness_mm）
2. 调用 heat_search 获取热处理价格信息
3. 调用 density_search 获取材料密度数据
4. 判断 needs_heat_treatment 是否为 True，如果不需要热处理则跳过
5. 根据 material 匹配 sub_category 获取单价（不区分大小写，支持材质别名映射）
6. 根据 material 匹配密度值（不区分大小写，支持材质别名映射）
7. 根据 job_id + subgraph_id 从 features 表读取 volume_mm3
8. 计算 NC 开粗后重量：nc_roughing_weight = density * volume_mm3
9. 计算热处理费：heat_treatment_cost = nc_roughing_weight * price
10. 更新 processing_cost_calculation_details 表和 subgraphs 表
"""
from typing import List, Dict, Any
from decimal import Decimal, ROUND_HALF_UP
import logging
import asyncio

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps
from .material_shape_helper import get_material_shape, get_shape_price_category

logger = logging.getLogger(__name__)

# 材质别名映射（用于材质适配）
MATERIAL_ALIASES = {
    "TOOLOX33": "T00L0X33",
    "TOOLOX44": "T00L0X44",
}

# 默认密度（钢材，当找不到匹配材料时使用）
DEFAULT_DENSITY = Decimal("0.00000785")
WEIGHT_PRECISION = Decimal("0.001")
MONEY_PRECISION = Decimal("0.01")

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_heat_treatment_cost",
    "description": "计算热处理费：根据零件信息、热处理价格和密度计算费用",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode、heat 和 density"
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
    "needs": ["base_itemcode", "heat", "density"]
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


async def _fetch_feature_volume_map(job_id: str, subgraph_ids: List[str]) -> Dict[str, Decimal]:
    """按 job_id + subgraph_id 批量读取 features.volume_mm3。"""
    if not subgraph_ids:
        return {}

    sql = """
        SELECT subgraph_id, volume_mm3
        FROM features
        WHERE job_id = $1::uuid
          AND subgraph_id = ANY($2::text[])
    """
    rows = await db.fetch_all(sql, job_id, subgraph_ids)
    return {
        row["subgraph_id"]: Decimal(str(row["volume_mm3"]))
        for row in rows
        if row["volume_mm3"] is not None
    }


async def _batch_update_subgraphs_heat(db_updates: List[Dict[str, Any]]):
    """批量回写 subgraphs 热处理单价、热处理费、NC开粗后重量。"""
    if not db_updates:
        return

    sql = """
        UPDATE subgraphs
        SET
            heat_treatment_unit_price = $3,
            heat_treatment_cost = $4,
            nc_roughing_weight = $5,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    await asyncio.gather(*[
        db.execute(
            sql,
            item["job_id"],
            item["subgraph_id"],
            item["heat_treatment_unit_price"],
            item["heat_treatment_cost"],
            item["nc_roughing_weight"],
        )
        for item in db_updates
    ])


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算热处理费
    
    Args:
        search_data: 检索数据，包含 base_itemcode、heat 和 density
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    heat_data = search_data["heat"]
    density_data = search_data["density"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating heat treatment cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 1: 构建密度映射表
    density_map = _build_density_map(density_data.get("density_data", []))
    
    # Step 2: 构建价格映射 (sub_category 转大写作为 key -> {price, unit})
    price_map = {}
    for price_item in heat_data.get("heat_prices", []):
        category = price_item.get("category", "heat")
        sub_category = price_item.get("sub_category")
        if category not in price_map:
            price_map[category] = {}
        # 转大写作为 key，实现不区分大小写匹配
        price_map[category][sub_category.upper()] = {
            "price": float(price_item.get("price", 0)),
            "unit": price_item.get("unit", ""),
            "original_sub_category": sub_category  # 保留原始值用于显示
        }
    
    # Step 3: 预取 features.volume_mm3，热处理统一基于 NC 开粗后体积计算
    volume_map = await _fetch_feature_volume_map(
        job_id,
        [part["subgraph_id"] for part in base_data.get("parts", [])]
    )

    # Step 4: 计算每个零件的热处理费（不写数据库）
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_cost(
            job_id, part, price_map, density_map, volume_map.get(part["subgraph_id"])
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
                "value": d["heat_treatment_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "heat", "heat_treatment_cost")
        await _batch_update_subgraphs_heat(db_updates)
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _calculate_part_cost(
    job_id: str,
    part: Dict,
    price_map: Dict,
    density_map: Dict[str, Decimal],
    volume_mm3: Decimal | None
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的热处理费
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    needs_heat_treatment = part.get("needs_heat_treatment")  # True/False
    material = part.get("material")  # 例如: CR12MOV
    length_mm = part.get("length_mm")
    width_mm = part.get("width_mm")
    thickness_mm = part.get("thickness_mm")
    
    logger.info(f"Calculating cost for part: {part_name} ({subgraph_id}), needs_heat_treatment: {needs_heat_treatment}, material: {material}")
    
    # 判断是否需要热处理
    if not needs_heat_treatment:
        logger.info(f"Part {part_name} does not need heat treatment, skipping")
        # 不需要热处理，返回结果和数据库更新数据
        result = {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "needs_heat_treatment": False,
            "heat_treatment_cost": 0.0,
            "note": "不需要热处理"
        }
        db_data = {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "heat_treatment_unit_price": 0.0,
            "nc_roughing_weight": None,
            "heat_treatment_cost": 0.0,
            "calculation_steps": [{
                "step": "判断是否需要热处理",
                "needs_heat_treatment": False,
                "heat_treatment_cost": 0.0,
                "note": "不需要热处理"
            }]
        }
        return result, db_data
    
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
            "needs_heat_treatment": True,
            "reason": f"缺少必需字段: {', '.join(missing)}",
            "missing_fields": missing,
            "heat_treatment_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "needs_heat_treatment": True,
            "heat_treatment_cost": 0.0,
            "note": f"缺少必需字段: {', '.join(missing)}"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "heat_treatment_unit_price": 0.0,
            "nc_roughing_weight": None,
            "heat_treatment_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    # 根据 material 匹配 sub_category（不区分大小写）
    if not material:
        logger.warning(f"material is empty for part: {part_name}, skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "数据验证",
            "status": "failed",
            "needs_heat_treatment": True,
            "reason": "material为空",
            "heat_treatment_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "needs_heat_treatment": True,
            "heat_treatment_cost": 0.0,
            "note": "material为空"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "heat_treatment_unit_price": 0.0,
            "nc_roughing_weight": None,
            "heat_treatment_cost": 0.0,
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
    price_category = get_shape_price_category(part, "heat", "r_heat")
    price_info = price_map.get(price_category, {}).get(material_mapped)
    if not price_info:
        logger.warning(f"No price found for material: {material} (mapped to: {material_mapped}), skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "匹配材料价格",
            "status": "failed",
            "needs_heat_treatment": True,
            "material": material,
            "mapped_material": material_mapped,
            "reason": f"未找到material对应的热处理价格: {material}",
            "heat_treatment_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "needs_heat_treatment": True,
            "material": material,
            "heat_treatment_cost": 0.0,
            "note": f"未找到material对应的热处理价格: {material}"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "heat_treatment_unit_price": 0.0,
            "nc_roughing_weight": None,
            "heat_treatment_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    unit_price = price_info["price"]
    unit = price_info["unit"]
    matched_sub_category = price_info.get("original_sub_category", material_mapped)
    
    # 获取材料密度
    density, matched_density_material = _get_material_density(material, density_map)

    if volume_mm3 is None:
        logger.warning(f"Missing features.volume_mm3 for {part_name} ({subgraph_id}), skipping calculation")

        calculation_steps = [{
            "step": "数据验证",
            "status": "failed",
            "needs_heat_treatment": True,
            "reason": "features.volume_mm3为空",
            "heat_treatment_cost": 0.0
        }]

        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "needs_heat_treatment": True,
            "material": material,
            "heat_treatment_cost": 0.0,
            "note": "features.volume_mm3为空"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "heat_treatment_unit_price": 0.0,
            "nc_roughing_weight": None,
            "heat_treatment_cost": 0.0,
            "calculation_steps": calculation_steps
        }

    nc_roughing_weight = (density * volume_mm3).quantize(
        WEIGHT_PRECISION, ROUND_HALF_UP
    )

    heat_treatment_cost = (nc_roughing_weight * Decimal(str(unit_price))).quantize(
        MONEY_PRECISION, ROUND_HALF_UP
    )
    
    calculation_steps = [
        {
            "step": "判断是否需要热处理",
            "needs_heat_treatment": True
        },
        {
            "step": "匹配材料",
            "material": material,
            "matched_sub_category": matched_sub_category,
            "match_note": f"不区分大小写匹配: {material} -> {matched_sub_category}",
            "unit_price": unit_price,
            "unit": unit
        },
        {
            "step": "匹配材料密度",
            "material": original_material,
            "matched_material": matched_density_material,
            "density": float(density),
            "unit": "g/cm³"
        },
        {
            "step": "读取开粗后体积",
            "volume_mm3": float(volume_mm3)
        },
        {
            "step": "计算NC开粗后重量",
            "formula": f"{density} * volume_mm3({volume_mm3})",
            "nc_roughing_weight": float(nc_roughing_weight)
        },
        {
            "step": "计算热处理费",
            "formula": f"{float(nc_roughing_weight)} * {unit_price}",
            "heat_treatment_cost": float(heat_treatment_cost)
        }
    ]
    
    logger.info(
        f"[{subgraph_id}] {part_name}: material={material}, nc_roughing_weight={nc_roughing_weight}, "
        f"unit_price={unit_price}, heat_treatment_cost={heat_treatment_cost}"
    )
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "needs_heat_treatment": True,
        "material": material,
        "volume_mm3": float(volume_mm3),
        "nc_roughing_weight": float(nc_roughing_weight),
        "unit_price": unit_price,
        "unit": unit,
        "heat_treatment_cost": float(heat_treatment_cost)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "heat_treatment_unit_price": unit_price,
        "nc_roughing_weight": float(nc_roughing_weight),
        "heat_treatment_cost": float(heat_treatment_cost),
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _update_calculation_details(
    job_id: str,
    subgraph_id: str,
    heat_treatment_cost: float,
    new_steps: List[Dict]
):
    """
    更新 processing_cost_calculation_details 表（保留用于向后兼容）
    """
    await batch_upsert_with_steps(
        [{
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "value": heat_treatment_cost,
            "steps": new_steps
        }],
        "heat",
        "heat_treatment_cost"
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
        print("Usage: python price_heat.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = calculate_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 计算结果 (job_id: {job_id}) ===")
    for result in results["results"]:
        if "error" in result:
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  错误: {result['error']}")
        elif not result.get("needs_heat_treatment"):
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  不需要热处理")
        else:
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  材料: {result['material']}")
            print(f"  开粗后体积: {result.get('volume_mm3')} mm³")
            print(f"  NC开粗后重量: {result.get('nc_roughing_weight')} kg")
            print(f"  单价: {result['unit_price']} {result['unit']}")
            print(f"  热处理费: {result['heat_treatment_cost']} 元")
