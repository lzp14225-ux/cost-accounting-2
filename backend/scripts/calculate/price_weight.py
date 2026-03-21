"""
重量计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（material, length_mm, width_mm, thickness_mm）
2. 调用 density_search 获取材料密度数据
3. 根据 material 匹配对应的密度值（不区分大小写，支持材质别名映射）
4. 计算公式: weight = density * length_mm * width_mm * thickness_mm
5. 更新表: subgraphs.weight_kg, features.calculated_weight_kg, processing_cost_calculation_details.weight
"""
from typing import List, Dict, Any, Optional
from decimal import Decimal, ROUND_HALF_UP
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_weight",
    "description": "重量计算：根据材料密度计算重量 weight = density * length_mm * width_mm * thickness_mm",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 density"
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
    "needs": ["base_itemcode", "density"]  # 声明依赖的数据类型
}

# 材质别名映射（用于材质适配）
MATERIAL_ALIASES = {
    "TOOLOX33": "T00L0X33",
    "TOOLOX44": "T00L0X44",
}

# 默认密度（钢材，当找不到匹配材料时使用）
DEFAULT_DENSITY = Decimal("0.00000785")


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算重量
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 density
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取零件基础信息和密度数据
    base_data = search_data["base_itemcode"]
    density_data = search_data["density"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating weight for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 1: 构建密度映射表
    density_map = _build_density_map(density_data.get("density_data", []))
    
    # Step 2: 计算每个零件的重量（不写数据库）
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_weight(job_id, part, density_map)
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # Step 3: 批量写入数据库
    if db_updates:
        # 更新 processing_cost_calculation_details 表（更新 weight 字段和 calculation_steps）
        updates_for_batch = [
            {
                "job_id": d["job_id"],
                "subgraph_id": d["subgraph_id"],
                "value": d["weight"],  # 传入计算的重量值
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "weight", "weight")
        
        # 然后批量更新 subgraphs 和 features 表
        await _batch_update_weight_tables(db_updates)
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
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


async def _calculate_part_weight(job_id: str, part: Dict, density_map: Dict[str, Decimal]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的重量
    
    公式: weight = density * length_mm * width_mm * thickness_mm
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    
    try:
        material = part.get("material", "")
        length_mm = part.get("length_mm")
        width_mm = part.get("width_mm")
        thickness_mm = part.get("thickness_mm")
        
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
                "weight": 0.0
            }]
            
            return {
                "subgraph_id": subgraph_id,
                "part_name": part_name,
                "weight": 0.0,
                "note": f"缺少必需字段: {', '.join(missing)}"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "weight": 0.0,
                "calculation_steps": calculation_steps
            }
        
        # 获取材料密度
        density, matched_material = _get_material_density(material, density_map)
        
        # 转换为 Decimal 进行精确计算
        length = Decimal(str(length_mm))
        width = Decimal(str(width_mm))
        thickness = Decimal(str(thickness_mm))
        
        # 计算重量: weight = density * length_mm * width_mm * thickness_mm
        weight = (density * length * width * thickness).quantize(
            Decimal("0.001"), ROUND_HALF_UP
        )
        
        # 构建计算步骤
        calculation_steps = [
            {
                "step": "获取零件信息",
                "material": material,
                "length_mm": float(length_mm),
                "width_mm": float(width_mm),
                "thickness_mm": float(thickness_mm)
            },
            {
                "step": "匹配材料密度",
                "material": material,
                "matched_material": matched_material,
                "density": float(density),
                "unit": "g/cm³"
            },
            {
                "step": "计算重量",
                "formula": f"{density} * {length_mm} * {width_mm} * {thickness_mm}",
                "weight": float(weight)
            }
        ]
        
        logger.info(
            f"[{subgraph_id}] {part_name}: length={length_mm}, width={width_mm}, "
            f"thickness={thickness_mm}, weight={weight}"
        )
        
        # 返回结果和数据库更新数据
        result = {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "length_mm": float(length_mm),
            "width_mm": float(width_mm),
            "thickness_mm": float(thickness_mm),
            "weight": float(weight)
        }
        
        db_data = {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "weight": float(weight),  # 添加重量值
            "calculation_steps": calculation_steps
        }
        
        return result, db_data
        
    except Exception as e:
        logger.error(f"Calculate weight error for {part_name}: {e}")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "error": str(e)
        }, None


async def _update_weight(job_id: str, subgraph_id: str, weight: float, new_steps: List[Dict]):
    """
    更新 processing_cost_calculation_details 表（已废弃，保留用于向后兼容）
    
    现在使用 batch_upsert_with_steps 函数
    """
    await batch_upsert_with_steps(
        [{
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "value": None,  # weight 不更新字段值
            "steps": new_steps
        }],
        "weight",
        None
    )


async def _batch_update_weight_tables(updates: List[Dict]):
    """
    批量更新 subgraphs 和 features 表的重量字段
    
    Args:
        updates: 更新数据列表，每项包含 job_id, subgraph_id, weight
    """
    logger.info(f"Batch updating weight for {len(updates)} records in subgraphs and features tables")
    
    tasks = []
    for data in updates:
        job_id = data["job_id"]
        subgraph_id = data["subgraph_id"]
        weight = data["weight"]
        
        # 更新 subgraphs 表
        sql_subgraphs = """
            UPDATE subgraphs SET
                weight_kg = $3,
                updated_at = NOW()
            WHERE job_id = $1::uuid AND subgraph_id = $2
        """
        tasks.append(db.execute(sql_subgraphs, job_id, subgraph_id, weight))
        
        # 更新 features 表
        sql_features = """
            UPDATE features SET
                calculated_weight_kg = $3
            WHERE job_id = $1::uuid AND subgraph_id = $2
        """
        tasks.append(db.execute(sql_features, job_id, subgraph_id, weight))
    
    try:
        await asyncio.gather(*tasks)
        logger.info(f"Successfully updated weight in subgraphs and features tables")
    except Exception as e:
        logger.error(f"Failed to batch update weight tables: {e}")
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
    
    if len(sys.argv) < 3:
        print("Usage: python price_weight.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 需要先获取检索数据
    async def main():
        from scripts.search.base_itemcode_search import search_by_job_id
        base_data = await search_by_job_id(job_id, subgraph_ids)
        
        search_data = {"base_itemcode": base_data}
        results = await calculate(search_data, job_id, subgraph_ids)
        
        print(f"\n=== 计算结果 (job_id: {job_id}) ===")
        for result in results["results"]:
            if "error" in result:
                print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
                print(f"  错误: {result['error']}")
            else:
                print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
                print(f"  尺寸: {result['length_mm']} x {result['width_mm']} x {result['thickness_mm']} mm")
                print(f"  重量: {result['weight']} kg")
    
    asyncio.run(main())

