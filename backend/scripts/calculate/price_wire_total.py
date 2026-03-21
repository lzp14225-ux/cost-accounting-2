"""
总价计算脚本
负责人：李志鹏

计算流程：
1. 从 base_itemcode_search.py 获取零件基础信息（包含 quantity、metadata）
2. 从 wire_total_search.py 获取成本明细（包含各项单价、calculation_steps）
3. 计算各项总价：
   - 总重量 = weight * quantity
   - 材料费 = material_cost * quantity
   - 热处理费 = heat_treatment_cost * quantity
   - 线割费用 = max(basic_processing_cost, special_base_cost, standard_base_cost) + material_additional_cost，然后 * quantity
4. 从 calculation_steps 中提取：
   - 材料单价（material 类别中的 unit_price）
   - 热处理单价（heat 类别中的 unit_price）
   - 线割类型（wire_special 类别中的 wire_type）
5. 从 metadata 中提取线割长度（top_view、side_view、front_view 的 total_length 相加）
6. 根据线割类型分配到对应字段（slow_wire_cost/mid_wire_cost/fast_wire_cost）
7. 批量更新 subgraphs 表
"""
from typing import List, Dict, Any
from decimal import Decimal, ROUND_HALF_UP
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_total_cost",
    "description": "计算总价：单价 × 数量，更新到 subgraphs 表",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 total"
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
    "needs": ["base_itemcode", "total"]  # 依赖两个检索结果
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算总价并更新 subgraphs 表
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 total
        job_id: 任务ID（可选）
        subgraph_ids: 子图ID列表（可选）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    total_data = search_data["total"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating total cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # 构建映射
    # 1. quantity_map: subgraph_id -> quantity
    quantity_map = {
        part["subgraph_id"]: part.get("quantity", 1)
        for part in base_data["parts"]
    }
    
    # 2. metadata_map: subgraph_id -> metadata
    metadata_map = {
        part["subgraph_id"]: part.get("metadata", {})
        for part in base_data["parts"]
    }
    
    # 3. cost_map: subgraph_id -> cost_details
    cost_map = {
        detail["subgraph_id"]: detail
        for detail in total_data["cost_details"]
    }
    
    # 计算各项总价
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_total(
            part, quantity_map, metadata_map, cost_map
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # 批量更新 subgraphs 表
    if db_updates:
        await _batch_update_subgraphs(job_id, db_updates)
        
        # 使用标准方法批量更新 calculation_steps
        updates_for_batch = [
            {
                "job_id": job_id,
                "subgraph_id": d["subgraph_id"],
                "value": None,  # wire_total 不需要更新字段值
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "wire_total", None)
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _calculate_part_total(
    part: Dict,
    quantity_map: Dict,
    metadata_map: Dict,
    cost_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的总价
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    quantity = quantity_map.get(subgraph_id, 1)
    metadata = metadata_map.get(subgraph_id, {})
    costs = cost_map.get(subgraph_id, {})
    
    logger.info(f"Calculating total for part: {part_name} ({subgraph_id}), quantity: {quantity}")
    
    # 获取各项单价
    weight = costs.get("weight", 0.0)
    material_cost = costs.get("material_cost", 0.0)
    heat_treatment_cost = costs.get("heat_treatment_cost", 0.0)
    material_additional_cost = costs.get("material_additional_cost", 0.0)
    basic_processing_cost = costs.get("basic_processing_cost", 0.0)
    special_base_cost = costs.get("special_base_cost", 0.0)
    standard_base_cost = costs.get("standard_base_cost", 0.0)
    tooth_hole_cost = costs.get("tooth_hole_cost", 0.0)  # 放电费用（元），从 total_search 返回
    tooth_hole_time_cost = costs.get("tooth_hole_time_cost", 0.0)  # 放电时间（小时），从 total_search 返回
    calculation_steps = costs.get("calculation_steps", [])
    
    # 1. 计算总重量：weight * quantity
    weight_kg = float(Decimal(str(weight)) * Decimal(str(quantity)))
    
    # 2. 计算材料费：material_cost * quantity
    material_cost_total = float(Decimal(str(material_cost)) * Decimal(str(quantity)))
    
    # 3. 计算热处理费：heat_treatment_cost * quantity
    heat_treatment_cost_total = float(Decimal(str(heat_treatment_cost)) * Decimal(str(quantity)))
    
    # 4. 计算自找料附加费总价（不需要乘以quantity，因为material_additional_cost已经是总价）
    material_additional_cost_total = float(material_additional_cost)
    
    # 5. 计算线割费用：max(basic_processing_cost, special_base_cost, standard_base_cost) + material_additional_cost
    # 注意：这里的 material_additional_cost 是单价，需要加到线割基础价格上，然后再乘以数量
    wire_cost_base = max(basic_processing_cost, special_base_cost, standard_base_cost)
    
    # 记录选择了哪个线割费用
    wire_cost_source = ""
    if wire_cost_base == basic_processing_cost:
        wire_cost_source = "basic_processing_cost"
    elif wire_cost_base == special_base_cost:
        wire_cost_source = "special_base_cost"
    elif wire_cost_base == standard_base_cost:
        wire_cost_source = "standard_base_cost"
    
    wire_cost_per_unit = wire_cost_base + material_additional_cost
    
    # 从 calculation_steps 中提取线割类型
    wire_type = _extract_wire_type(calculation_steps)
    
    # 根据线割类型分配费用（单价 * 数量）
    slow_wire_cost = 0.0
    mid_wire_cost = 0.0
    fast_wire_cost = 0.0
    
    if wire_type == "慢丝":
        slow_wire_cost = float(Decimal(str(wire_cost_per_unit)) * Decimal(str(quantity)))
    elif wire_type == "中丝":
        mid_wire_cost = float(Decimal(str(wire_cost_per_unit)) * Decimal(str(quantity)))
    elif wire_type == "快丝":
        fast_wire_cost = float(Decimal(str(wire_cost_per_unit)) * Decimal(str(quantity)))
    else:
        # 如果没有线割类型，默认放到快丝
        fast_wire_cost = float(Decimal(str(wire_cost_per_unit)) * Decimal(str(quantity)))
    
    # 6. 提取材料单价
    material_unit_price = _extract_unit_price(calculation_steps, "material")
    
    # 7. 提取热处理单价
    heat_treatment_unit_price = _extract_unit_price(calculation_steps, "heat")
    
    # 8. 提取线割长度（从 metadata.wire_cut_details 中提取 top_view、side_view、front_view 的 total_length 相加）
    wire_length = _extract_wire_length(metadata)
    slow_wire_length = 0.0
    mid_wire_length = 0.0
    fast_wire_length = 0.0
    
    if wire_type == "慢丝":
        slow_wire_length = wire_length
    elif wire_type == "中丝":
        mid_wire_length = wire_length
    elif wire_type == "快丝":
        fast_wire_length = wire_length
    else:
        fast_wire_length = wire_length
    
    # 构建计算步骤
    wire_total_calculation_steps = [
        {
            "step": "获取单价数据",
            "weight": weight,
            "material_cost": material_cost,
            "heat_treatment_cost": heat_treatment_cost,
            "material_additional_cost": material_additional_cost,
            "basic_processing_cost": basic_processing_cost,
            "special_base_cost": special_base_cost,
            "standard_base_cost": standard_base_cost
        },
        {
            "step": "计算线割基础费用",
            "formula": f"max({basic_processing_cost}, {special_base_cost}, {standard_base_cost})",
            "basic_processing_cost": basic_processing_cost,
            "special_base_cost": special_base_cost,
            "standard_base_cost": standard_base_cost,
            "selected": wire_cost_source,
            "wire_cost_base": wire_cost_base,
            "note": f"选择了 {wire_cost_source} = {wire_cost_base}"
        },
        {
            "step": "计算线割单价",
            "formula": f"{wire_cost_base} + {material_additional_cost}",
            "wire_cost_base": wire_cost_base,
            "material_additional_cost": material_additional_cost,
            "wire_cost_per_unit": wire_cost_per_unit
        },
        {
            "step": "确定线割类型",
            "wire_type": wire_type,
            "note": f"从calculation_steps中提取，类型为: {wire_type}"
        },
        {
            "step": "计算线割总价",
            "formula": f"{wire_cost_per_unit} * {quantity}",
            "wire_cost_per_unit": wire_cost_per_unit,
            "quantity": quantity,
            "slow_wire_cost": slow_wire_cost,
            "mid_wire_cost": mid_wire_cost,
            "fast_wire_cost": fast_wire_cost,
            "note": f"{wire_type}费用 = {wire_cost_per_unit} * {quantity}"
        },
        {
            "step": "计算其他总价",
            "weight_kg": weight_kg,
            "material_cost_total": material_cost_total,
            "heat_treatment_cost_total": heat_treatment_cost_total,
            "formulas": {
                "weight_kg": f"{weight} * {quantity}",
                "material_cost": f"{material_cost} * {quantity}",
                "heat_treatment_cost": f"{heat_treatment_cost} * {quantity}"
            }
        },
        {
            "step": "提取单价和长度",
            "material_unit_price": material_unit_price,
            "heat_treatment_unit_price": heat_treatment_unit_price,
            "wire_length": wire_length,
            "slow_wire_length": slow_wire_length,
            "mid_wire_length": mid_wire_length,
            "fast_wire_length": fast_wire_length
        }
    ]
    
    # 构建结果
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "quantity": quantity,
        "weight_kg": weight_kg,
        "material_cost": material_cost_total,
        "heat_treatment_cost": heat_treatment_cost_total,
        "material_additional_cost": material_additional_cost_total,
        "slow_wire_cost": slow_wire_cost,
        "mid_wire_cost": mid_wire_cost,
        "fast_wire_cost": fast_wire_cost,
        "material_unit_price": material_unit_price,
        "heat_treatment_unit_price": heat_treatment_unit_price,
        "slow_wire_length": slow_wire_length,
        "mid_wire_length": mid_wire_length,
        "fast_wire_length": fast_wire_length,
        "wire_type": wire_type,
        "wire_cost_source": wire_cost_source,  # 新增：记录选择了哪个线割费用
        "edm_time": tooth_hole_time_cost,  # tooth_hole_time_cost（小时）对应 edm_time
        "edm_cost": tooth_hole_cost  # tooth_hole_cost（元）对应 edm_cost
    }
    
    db_data = {
        "subgraph_id": subgraph_id,
        "weight_kg": weight_kg,
        "material_cost": material_cost_total,
        "heat_treatment_cost": heat_treatment_cost_total,
        "slow_wire_cost": slow_wire_cost,
        "mid_wire_cost": mid_wire_cost,
        "fast_wire_cost": fast_wire_cost,
        "material_unit_price": material_unit_price,
        "heat_treatment_unit_price": heat_treatment_unit_price,
        "slow_wire_length": slow_wire_length,
        "mid_wire_length": mid_wire_length,
        "fast_wire_length": fast_wire_length,
        "edm_time": tooth_hole_time_cost,  # tooth_hole_time_cost（小时）对应 edm_time
        "edm_cost": tooth_hole_cost,  # tooth_hole_cost（元）对应 edm_cost
        "calculation_steps": wire_total_calculation_steps  # 新增：计算步骤
    }
    
    logger.info(
        f"[{subgraph_id}] {part_name}: quantity={quantity}, weight_kg={weight_kg:.3f}, "
        f"material_cost={material_cost_total:.2f}, heat_treatment_cost={heat_treatment_cost_total:.2f}, "
        f"wire_type={wire_type}, wire_cost_source={wire_cost_source}, wire_cost_per_unit={wire_cost_per_unit:.2f}"
    )
    
    return result, db_data


def _extract_wire_type(calculation_steps: List[Dict]) -> str:
    """
    从 calculation_steps 中提取线割类型
    
    查找 category 为 wire_special 的步骤，提取 wire_type
    例如：[5] 类别: wire_special，步骤 1: 判断线割类型 - wire_type: slow
    
    将英文值转换为中文：slow -> 慢丝, mid/medium -> 中丝, fast -> 快丝
    """
    # 英文到中文的映射
    wire_type_map = {
        "slow": "慢丝",
        "mid": "中丝",
        "medium": "中丝",  # 添加 medium 的支持
        "middle": "中丝",  # 添加 middle 的支持
        "fast": "快丝"
    }
    
    for step_category in calculation_steps:
        if isinstance(step_category, dict):
            category = step_category.get("category", "")
            # 查找 wire_special 或 wire_base 类别
            if category in ["wire_special", "wire_speci", "wire_base"]:
                steps = step_category.get("steps", [])
                for step in steps:
                    if isinstance(step, dict):
                        step_name = step.get("step", "")
                        # 查找包含"判断线割类型"的步骤，或直接包含 wire_type 字段
                        if "判断线割类型" in step_name or "wire_type" in step:
                            wire_type = step.get("wire_type", "")
                            if wire_type:
                                # 转换为中文
                                return wire_type_map.get(wire_type, wire_type)
    return ""


def _extract_unit_price(calculation_steps: List[Dict], category_name: str) -> float:
    """
    从 calculation_steps 中提取单价
    
    Args:
        calculation_steps: 计算步骤
        category_name: 类别名称（material 或 heat）
    
    Returns:
        float: 单价
    """
    for step_category in calculation_steps:
        if isinstance(step_category, dict):
            category = step_category.get("category", "")
            if category == category_name:
                steps = step_category.get("steps", [])
                for step in steps:
                    if isinstance(step, dict):
                        step_name = step.get("step", "")
                        if "匹配材料" in step_name:
                            unit_price = step.get("unit_price", 0.0)
                            if unit_price:
                                return float(unit_price)
    return 0.0


def _extract_wire_length_from_steps(calculation_steps: List[Dict]) -> float:
    """
    从 calculation_steps 中提取线割长度（已废弃）
    
    现在使用 _extract_wire_length 从 metadata.wire_cut_details 中提取
    """
    if not calculation_steps:
        return 0.0
    
    # 查找 wire_base 类别
    for step_category in calculation_steps:
        if isinstance(step_category, dict):
            category = step_category.get("category", "")
            if category == "wire_base":
                steps = step_category.get("steps", [])
                # 查找 top_view 的 total_length
                for step in steps:
                    if isinstance(step, dict):
                        view = step.get("view", "")
                        if view == "top_view":
                            total_length = step.get("total_length", 0.0)
                            if total_length:
                                return float(total_length)
    
    return 0.0


def _extract_wire_length(metadata: Dict) -> float:
    """
    从 metadata.wire_cut_details 中提取线割长度
    
    累加所有 view 为 top_view、side_view、front_view 的 total_length
    """
    if not metadata:
        return 0.0
    
    # metadata 可能是字符串，需要解析
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning("Failed to parse metadata as JSON")
            return 0.0
    
    # 从 wire_cut_details 中提取 top_view、side_view、front_view 的 total_length
    if isinstance(metadata, dict):
        wire_cut_details = metadata.get("wire_cut_details", [])
        total_length = 0.0
        
        for detail in wire_cut_details:
            if isinstance(detail, dict):
                view = detail.get("view", "")
                if view in ["top_view", "side_view", "front_view"]:
                    length = detail.get("total_length", 0.0)
                    if length:
                        total_length += float(length)
        
        return total_length
    
    return 0.0


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
            weight_kg = $3,
            material_cost = $4,
            heat_treatment_cost = $5,
            slow_wire_cost = $6,
            mid_wire_cost = $7,
            fast_wire_cost = $8,
            material_unit_price = $9,
            heat_treatment_unit_price = $10,
            slow_wire_length = $11,
            mid_wire_length = $12,
            fast_wire_length = $13,
            edm_time = $14,
            edm_cost = $15,
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
                data["weight_kg"],
                data["material_cost"],
                data["heat_treatment_cost"],
                data["slow_wire_cost"],
                data["mid_wire_cost"],
                data["fast_wire_cost"],
                data["material_unit_price"],
                data["heat_treatment_unit_price"],
                data["slow_wire_length"],
                data["mid_wire_length"],
                data["fast_wire_length"],
                data["edm_time"],
                data["edm_cost"]
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
    
    print("price_wire_total.py - 总价计算脚本")
    print("需要配合 base_itemcode_search.py 和 wire_total_search.py 使用")
    print("\n使用方式：")
    print("1. 先执行 base_itemcode_search.py 获取零件信息")
    print("2. 再执行 wire_total_search.py 获取成本明细")
    print("3. 最后调用本脚本计算总价并更新 subgraphs 表")
