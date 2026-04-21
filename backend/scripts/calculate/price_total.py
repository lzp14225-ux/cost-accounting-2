"""
最终总价计算脚本（阶段 8）
负责人：李志鹏

计算流程：
1. 从 search.py (subgraphs_cost_search) 获取各项成本
2. 计算加工成本总计：large_grinding_cost + small_grinding_cost + slow_wire_cost + 
                    slow_wire_side_cost + mid_wire_cost + fast_wire_cost + edm_cost +
                    nc_z_fee + nc_b_fee + nc_c_fee + nc_c_b_fee + nc_z_view_fee + nc_b_view_fee
3. 计算总价：material_cost + heat_treatment_cost + processing_cost_total
4. 更新 subgraphs 表的 total_cost 和 processing_cost_total 字段
5. 生成并更新工艺描述（process_description）
6. 累加所有 subgraph 的 total_cost，更新 jobs 表的 total_cost 字段

执行顺序：
阶段 7: 数据清理和校验 (judgment.py) ← 先执行
阶段 8: 最终总价计算 (本脚本) ← 后执行
"""
from typing import List, Dict, Any, Set
from decimal import Decimal, InvalidOperation
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

EXPORT_EXCLUDE_KEYWORDS = ["订购", "附图订购", "二次加工", "钣金"]

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_final_total_cost",
    "description": "计算最终总价和加工成本总计：汇总所有成本项，更新 subgraphs 表和 jobs 表（在 judgment_cleanup 之后执行）",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 subgraphs_cost"
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
    "needs": ["subgraphs_cost", "base_itemcode"],
    "depends_on": ["search_subgraphs_cost_by_job_id", "search_base_itemcode_by_job_id", "judgment_cleanup"]  # 依赖 judgment_cleanup 和 base_itemcode_search
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算最终总价并更新 subgraphs 表，然后累加更新 jobs 表
    
    Args:
        search_data: 检索数据，包含 subgraphs_cost 和 base_itemcode
        job_id: 任务ID（可选）
        subgraph_ids: 子图ID列表（可选）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    subgraphs_cost_data = search_data.get("subgraphs_cost")
    base_itemcode_data = search_data.get("base_itemcode")
    
    if not subgraphs_cost_data:
        logger.warning("Missing subgraphs_cost data, skipping final total cost calculation")
        return {
            "job_id": job_id if job_id else "unknown",
            "job_total_cost": 0.0,
            "parts_count": 0,
            "results": [],
            "note": "缺少 subgraphs_cost 数据，跳过最终总价计算"
        }
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = subgraphs_cost_data.get("job_id")
    
    cost_summary = subgraphs_cost_data.get("cost_summary", [])
    
    # 构建基础映射（subgraph_id -> nc_time_cost / quantity）
    nc_time_cost_map = {}
    quantity_map = {}
    if base_itemcode_data and "parts" in base_itemcode_data:
        for part in base_itemcode_data["parts"]:
            nc_time_cost_map[part["subgraph_id"]] = part.get("nc_time_cost")
            quantity = part.get("quantity") or 1
            try:
                quantity_map[part["subgraph_id"]] = max(int(quantity), 1)
            except (TypeError, ValueError):
                quantity_map[part["subgraph_id"]] = 1
    
    excluded_subgraph_ids = await _get_excluded_subgraph_ids_for_job_total(job_id, cost_summary)

    logger.info(
        f"Calculating final total cost for job_id: {job_id}, parts count: {len(cost_summary)}, "
        f"excluded_from_job_total={len(excluded_subgraph_ids)}"
    )
    
    # 计算每个零件的总价
    results = []
    db_updates = []
    job_total_cost = Decimal("0")  # 累加所有零件的总价
    
    for summary in cost_summary:
        subgraph_id = summary["subgraph_id"]
        nc_time_cost = nc_time_cost_map.get(subgraph_id)
        quantity = quantity_map.get(subgraph_id, 1)

        result, db_data = _calculate_part_total(summary, nc_time_cost, quantity)
        results.append(result)
        if db_data:
            db_updates.append(db_data)
            if subgraph_id not in excluded_subgraph_ids:
                job_total_cost += Decimal(str(db_data["total_cost"]))
    
    # 批量更新 subgraphs 表
    if db_updates:
        await _batch_update_subgraphs(job_id, db_updates)
    
    # 生成并更新工艺描述
    await _update_process_descriptions(job_id, [data["subgraph_id"] for data in db_updates], nc_time_cost_map)
    
    # 更新 jobs 表的 total_cost
    job_total_cost_float = float(job_total_cost)
    await _update_job_total_cost(job_id, job_total_cost_float)
    
    logger.info(f"Completed calculation for {len(results)} parts, job total_cost: {job_total_cost_float:.2f}")
    
    return {
        "job_id": job_id,
        "job_total_cost": job_total_cost_float,
        "parts_count": len(results),
        "results": results
    }


def _contains_export_exclude_keyword(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in EXPORT_EXCLUDE_KEYWORDS)


def _flatten_processing_instructions(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(_flatten_processing_instructions(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_processing_instructions(item) for item in value)
    return str(value)


async def _should_exclude_from_job_total(summary: Dict[str, Any], feature_row: Dict[str, Any]) -> bool:
    part_name = str(summary.get("part_name") or "").strip()
    if _contains_export_exclude_keyword(part_name):
        return True

    processing_text = _flatten_processing_instructions(
        (feature_row or {}).get("processing_instructions")
    )
    return _contains_export_exclude_keyword(processing_text)


async def _get_excluded_subgraph_ids_for_job_total(
    job_id: str,
    cost_summary: List[Dict[str, Any]],
) -> Set[str]:
    if not job_id or not cost_summary:
        return set()

    subgraph_ids = [
        str(item.get("subgraph_id") or "").strip()
        for item in cost_summary
        if str(item.get("subgraph_id") or "").strip()
    ]
    if not subgraph_ids:
        return set()

    sql = """
        SELECT s.subgraph_id, s.part_name, f.processing_instructions
        FROM subgraphs s
        LEFT JOIN features f
            ON s.job_id = f.job_id AND s.subgraph_id = f.subgraph_id
        WHERE s.job_id = $1::uuid AND s.subgraph_id = ANY($2::text[])
    """
    rows = await db.fetch_all(sql, job_id, subgraph_ids)
    feature_map = {
        str(row["subgraph_id"]): dict(row)
        for row in rows
        if row.get("subgraph_id") is not None
    }

    tasks = [
        _should_exclude_from_job_total(summary, feature_map.get(summary["subgraph_id"], {}))
        for summary in cost_summary
        if summary.get("subgraph_id")
    ]
    decisions = await asyncio.gather(*tasks)

    excluded_subgraph_ids = {
        str(summary["subgraph_id"])
        for summary, should_exclude in zip(
            [item for item in cost_summary if item.get("subgraph_id")],
            decisions
        )
        if should_exclude
    }

    if excluded_subgraph_ids:
        logger.info(
            "Excluded subgraphs from job total by export filter: %s",
            sorted(excluded_subgraph_ids),
        )

    return excluded_subgraph_ids


def _safe_divide_decimal(value: Decimal, divisor: int) -> Decimal:
    """安全除法：数量异常时回退为 1，避免单件价格计算崩溃。"""
    safe_divisor = divisor if isinstance(divisor, int) and divisor > 0 else 1
    return value / Decimal(str(safe_divisor))


def _calculate_part_total(summary: Dict, nc_time_cost: Any = None, quantity: int = 1) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的最终总价和加工成本总计
    
    Args:
        summary: 成本汇总数据
        nc_time_cost: NC时间成本数据（用于判断工艺）
        
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = summary["subgraph_id"]
    quantity = quantity if isinstance(quantity, int) and quantity > 0 else 1
    
    # 获取各项成本，添加异常处理
    try:
        material_cost = Decimal(str(summary.get("material_cost", 0)))
        heat_treatment_cost = Decimal(str(summary.get("heat_treatment_cost", 0)))
        large_grinding_cost = Decimal(str(summary.get("large_grinding_cost", 0)))
        small_grinding_cost = Decimal(str(summary.get("small_grinding_cost", 0)))
        slow_wire_cost = Decimal(str(summary.get("slow_wire_cost", 0)))
        slow_wire_side_cost = Decimal(str(summary.get("slow_wire_side_cost", 0)))
        mid_wire_cost = Decimal(str(summary.get("mid_wire_cost", 0)))
        fast_wire_cost = Decimal(str(summary.get("fast_wire_cost", 0)))
        edm_cost = Decimal(str(summary.get("edm_cost", 0)))
        nc_z_fee = Decimal(str(summary.get("nc_z_fee", 0)))
        nc_b_fee = Decimal(str(summary.get("nc_b_fee", 0)))
        nc_c_fee = Decimal(str(summary.get("nc_c_fee", 0)))
        nc_c_b_fee = Decimal(str(summary.get("nc_c_b_fee", 0)))
        nc_z_view_fee = Decimal(str(summary.get("nc_z_view_fee", 0)))
        nc_b_view_fee = Decimal(str(summary.get("nc_b_view_fee", 0)))
    except (ValueError, TypeError, InvalidOperation) as e:
        logger.error(f"Failed to convert cost values to Decimal for {subgraph_id}: {e}")
        # 返回 0 并记录错误
        calculation_steps = [{
            "step": "数据转换",
            "status": "failed",
            "reason": f"成本数据转换失败: {str(e)}",
            "total_cost": 0.0,
            "processing_cost_total": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "quantity": quantity,
            "total_cost": 0.0,
            "processing_cost_total": 0.0,
            "note": f"成本数据转换失败: {str(e)}"
        }, {
            "subgraph_id": subgraph_id,
            "total_cost": 0.0,
            "processing_cost_total": 0.0,
            "calculation_steps": calculation_steps
        }
    
    # 计算加工成本总计（不包含材料成本和热处理成本）
    processing_cost_total = (
        large_grinding_cost + 
        small_grinding_cost + 
        slow_wire_cost + 
        slow_wire_side_cost + 
        mid_wire_cost + 
        fast_wire_cost + 
        edm_cost +
        nc_z_fee +
        nc_b_fee +
        nc_c_fee +
        nc_c_b_fee +
        nc_z_view_fee +
        nc_b_view_fee
    )
    
    # 计算总价
    total_cost = (
        material_cost + 
        heat_treatment_cost + 
        processing_cost_total
    )
    
    total_cost_float = float(total_cost)
    processing_cost_total_float = float(processing_cost_total)

    single_material_cost = _safe_divide_decimal(material_cost, quantity)
    single_heat_treatment_cost = _safe_divide_decimal(heat_treatment_cost, quantity)
    single_processing_cost_total = _safe_divide_decimal(processing_cost_total, quantity)
    single_total_cost = _safe_divide_decimal(total_cost, quantity)

    single_breakdown = {
        "material_cost_single": float(single_material_cost),
        "heat_treatment_cost_single": float(single_heat_treatment_cost),
        "processing_cost_total_single": float(single_processing_cost_total),
        "large_grinding_cost_single": float(_safe_divide_decimal(large_grinding_cost, quantity)),
        "small_grinding_cost_single": float(_safe_divide_decimal(small_grinding_cost, quantity)),
        "slow_wire_cost_single": float(_safe_divide_decimal(slow_wire_cost, quantity)),
        "slow_wire_side_cost_single": float(_safe_divide_decimal(slow_wire_side_cost, quantity)),
        "mid_wire_cost_single": float(_safe_divide_decimal(mid_wire_cost, quantity)),
        "fast_wire_cost_single": float(_safe_divide_decimal(fast_wire_cost, quantity)),
        "edm_cost_single": float(_safe_divide_decimal(edm_cost, quantity)),
        "nc_z_fee_single": float(_safe_divide_decimal(nc_z_fee, quantity)),
        "nc_b_fee_single": float(_safe_divide_decimal(nc_b_fee, quantity)),
        "nc_c_fee_single": float(_safe_divide_decimal(nc_c_fee, quantity)),
        "nc_c_b_fee_single": float(_safe_divide_decimal(nc_c_b_fee, quantity)),
        "nc_z_view_fee_single": float(_safe_divide_decimal(nc_z_view_fee, quantity)),
        "nc_b_view_fee_single": float(_safe_divide_decimal(nc_b_view_fee, quantity)),
        "cost_single": float(single_total_cost),
    }
    
    logger.info(
        f"[{subgraph_id}] total_cost={total_cost_float:.2f}, processing_cost_total={processing_cost_total_float:.2f} "
        f"(material={float(material_cost):.2f} + heat={float(heat_treatment_cost):.2f} + "
        f"large_grinding={float(large_grinding_cost):.2f} + small_grinding={float(small_grinding_cost):.2f} + "
        f"slow_wire={float(slow_wire_cost):.2f} + slow_wire_side={float(slow_wire_side_cost):.2f} + "
        f"mid_wire={float(mid_wire_cost):.2f} + fast_wire={float(fast_wire_cost):.2f} + "
        f"edm={float(edm_cost):.2f} + nc_z={float(nc_z_fee):.2f} + nc_b={float(nc_b_fee):.2f} + "
        f"nc_c={float(nc_c_fee):.2f} + nc_c_b={float(nc_c_b_fee):.2f} + "
        f"nc_z_view={float(nc_z_view_fee):.2f} + nc_b_view={float(nc_b_view_fee):.2f})"
    )
    
    # 构建计算步骤
    calculation_steps = []
    
    # 步骤1: 获取各项成本
    cost_items = {
        "material_cost": float(material_cost),
        "heat_treatment_cost": float(heat_treatment_cost),
        "large_grinding_cost": float(large_grinding_cost),
        "small_grinding_cost": float(small_grinding_cost),
        "slow_wire_cost": float(slow_wire_cost),
        "slow_wire_side_cost": float(slow_wire_side_cost),
        "mid_wire_cost": float(mid_wire_cost),
        "fast_wire_cost": float(fast_wire_cost),
        "edm_cost": float(edm_cost),
        "nc_z_fee": float(nc_z_fee),
        "nc_b_fee": float(nc_b_fee),
        "nc_c_fee": float(nc_c_fee),
        "nc_c_b_fee": float(nc_c_b_fee),
        "nc_z_view_fee": float(nc_z_view_fee),
        "nc_b_view_fee": float(nc_b_view_fee)
    }
    
    calculation_steps.append({
        "step": "获取各项成本",
        "quantity": quantity,
        **cost_items
    })
    
    # 步骤2: 计算加工成本总计
    processing_items = []
    processing_values = []
    
    if float(large_grinding_cost) > 0:
        processing_items.append("大水磨")
        processing_values.append(f"{float(large_grinding_cost):.2f}")
    if float(small_grinding_cost) > 0:
        processing_items.append("小水磨")
        processing_values.append(f"{float(small_grinding_cost):.2f}")
    if float(slow_wire_cost) > 0:
        processing_items.append("慢丝")
        processing_values.append(f"{float(slow_wire_cost):.2f}")
    if float(slow_wire_side_cost) > 0:
        processing_items.append("慢丝侧割")
        processing_values.append(f"{float(slow_wire_side_cost):.2f}")
    if float(mid_wire_cost) > 0:
        processing_items.append("中丝")
        processing_values.append(f"{float(mid_wire_cost):.2f}")
    if float(fast_wire_cost) > 0:
        processing_items.append("快丝")
        processing_values.append(f"{float(fast_wire_cost):.2f}")
    if float(edm_cost) > 0:
        processing_items.append("EDM")
        processing_values.append(f"{float(edm_cost):.2f}")
    if float(nc_z_fee) > 0:
        processing_items.append("NC主视图")
        processing_values.append(f"{float(nc_z_fee):.2f}")
    if float(nc_b_fee) > 0:
        processing_items.append("NC背面")
        processing_values.append(f"{float(nc_b_fee):.2f}")
    if float(nc_c_fee) > 0:
        processing_items.append("NC侧面正面")
        processing_values.append(f"{float(nc_c_fee):.2f}")
    if float(nc_c_b_fee) > 0:
        processing_items.append("NC侧背")
        processing_values.append(f"{float(nc_c_b_fee):.2f}")
    if float(nc_z_view_fee) > 0:
        processing_items.append("NC正面")
        processing_values.append(f"{float(nc_z_view_fee):.2f}")
    if float(nc_b_view_fee) > 0:
        processing_items.append("NC正面的背面")
        processing_values.append(f"{float(nc_b_view_fee):.2f}")
    
    if processing_values:
        formula = " + ".join(processing_values) + f" = {processing_cost_total_float:.2f}"
    else:
        formula = "0（无加工费用）"
    
    calculation_steps.append({
        "step": "计算加工成本总计",
        "note": "不包含材料成本和热处理成本",
        "items": processing_items if processing_items else ["无"],
        "formula": formula,
        "processing_cost_total": processing_cost_total_float
    })
    
    # 步骤3: 计算总价
    total_items = []
    total_values = []
    
    if float(material_cost) > 0:
        total_items.append("材料费")
        total_values.append(f"{float(material_cost):.2f}")
    if float(heat_treatment_cost) > 0:
        total_items.append("热处理费")
        total_values.append(f"{float(heat_treatment_cost):.2f}")
    if processing_cost_total_float > 0:
        total_items.append("加工费")
        total_values.append(f"{processing_cost_total_float:.2f}")
    
    if total_values:
        total_formula = " + ".join(total_values) + f" = {total_cost_float:.2f}"
    else:
        total_formula = "0（无费用）"
    
    calculation_steps.append({
        "step": "计算总价",
        "items": total_items if total_items else ["无"],
        "formula": total_formula,
        "total_cost": total_cost_float
    })

    calculation_steps.append({
        "step": "计算单件价格",
        "note": "将当前零件整批费用按数量平摊得到单件费用",
        "quantity": quantity,
        "material_cost_single": float(single_material_cost),
        "heat_treatment_cost_single": float(single_heat_treatment_cost),
        "processing_cost_total_single": float(single_processing_cost_total),
        "large_grinding_cost_single": single_breakdown["large_grinding_cost_single"],
        "small_grinding_cost_single": single_breakdown["small_grinding_cost_single"],
        "slow_wire_cost_single": single_breakdown["slow_wire_cost_single"],
        "slow_wire_side_cost_single": single_breakdown["slow_wire_side_cost_single"],
        "mid_wire_cost_single": single_breakdown["mid_wire_cost_single"],
        "fast_wire_cost_single": single_breakdown["fast_wire_cost_single"],
        "edm_cost_single": single_breakdown["edm_cost_single"],
        "nc_z_fee_single": single_breakdown["nc_z_fee_single"],
        "nc_b_fee_single": single_breakdown["nc_b_fee_single"],
        "nc_c_fee_single": single_breakdown["nc_c_fee_single"],
        "nc_c_b_fee_single": single_breakdown["nc_c_b_fee_single"],
        "nc_z_view_fee_single": single_breakdown["nc_z_view_fee_single"],
        "nc_b_view_fee_single": single_breakdown["nc_b_view_fee_single"],
        "formula_single": f"{total_cost_float:.2f} / {quantity} = {float(single_total_cost):.2f}",
        "cost_single": float(single_total_cost)
    })
    
    # 返回结果
    result = {
        "subgraph_id": subgraph_id,
        "quantity": quantity,
        "total_cost": total_cost_float,
        "cost_single": float(single_total_cost),
        "processing_cost_total": processing_cost_total_float,
        "processing_cost_total_single": float(single_processing_cost_total),
        "breakdown": {
            **cost_items,
            **single_breakdown
        }
    }
    
    db_data = {
        "subgraph_id": subgraph_id,
        "total_cost": total_cost_float,
        "processing_cost_total": processing_cost_total_float,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _batch_update_subgraphs(job_id: str, updates: List[Dict]):
    """
    批量更新 subgraphs 表的 total_cost 和 processing_cost_total 字段
    同时更新 processing_cost_calculation_details 表的计算步骤
    
    Args:
        job_id: 任务ID
        updates: 更新数据列表（包含 calculation_steps）
    """
    logger.info(f"Batch updating {len(updates)} records to subgraphs table")
    
    # 1. 更新 subgraphs 表
    sql = """
        UPDATE subgraphs
        SET 
            total_cost = $3,
            processing_cost_total = $4,
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
                data["total_cost"],
                data["processing_cost_total"]
            ))
        
        await asyncio.gather(*tasks)
        logger.info(f"Successfully updated {len(updates)} records in subgraphs table")
    
    except Exception as e:
        logger.error(f"Failed to batch update subgraphs: {e}")
        raise
    
    # 2. 更新 processing_cost_calculation_details 表的计算步骤
    try:
        from ._batch_update_helper import batch_upsert_with_steps
        
        updates_for_batch = [
            {
                "job_id": job_id,
                "subgraph_id": d["subgraph_id"],
                "value": d["total_cost"],
                "steps": d["calculation_steps"]
            }
            for d in updates
        ]
        
        await batch_upsert_with_steps(updates_for_batch, "total", "total_cost")
        logger.info(f"Successfully updated calculation steps for {len(updates)} records")
    
    except Exception as e:
        logger.error(f"Failed to update calculation steps: {e}")
        # 不抛出异常，因为主要数据已经更新成功
        logger.warning("Calculation steps update failed, but main data is updated")


async def _update_job_total_cost(job_id: str, total_cost: float):
    """
    更新 jobs 表的 total_cost 字段
    
    Args:
        job_id: 任务ID
        total_cost: 累加后的总成本
    """
    logger.info(f"Updating jobs table for job_id: {job_id}, total_cost: {total_cost:.2f}")
    
    sql = """
        UPDATE jobs
        SET 
            total_cost = $2,
            updated_at = NOW()
        WHERE job_id = $1::uuid
    """
    
    try:
        await db.execute(sql, job_id, total_cost)
        logger.info(f"Successfully updated jobs table, job_id: {job_id}, total_cost: {total_cost:.2f}")
    
    except Exception as e:
        logger.error(f"Failed to update jobs table: {e}")
        raise


async def _update_process_descriptions(job_id: str, subgraph_ids: List[str], nc_time_cost_map: Dict[str, Any]):
    """
    生成并更新工艺描述（process_description）
    
    工艺字段映射：
    - NC工艺（从nc_time_cost判断）：
      - S: 开粗（code为"开粗"）
      - SS: 精铣（code为"精铣"、"半精"、"全精"）
      - Z: 钻床（其他所有code，如M、T、L、A、D等）
    - heat_treatment ->
      - HRC -> ZKR
      - 调质 -> 调质
      - 激光 -> 激光
      - 深冷 -> 深冷
    - large_grinding_cost -> M
    - small_grinding_cost -> YM
    - slow_wire_length -> WE
    - mid_wire_length -> WZ
    - fast_wire_length -> WC
    - edm_time -> EDM
    - engraving_cost -> DK
    
    最后固定添加 QC
    
    Args:
        job_id: 任务ID
        subgraph_ids: 子图ID列表
        nc_time_cost_map: NC时间成本映射（subgraph_id -> nc_time_cost）
    """
    logger.info(f"Generating process descriptions for {len(subgraph_ids)} parts")
    
    # 工艺字段映射（按顺序，不包含NC和热处理）
    process_fields = [
        ("large_grinding_cost", "M"),
        ("small_grinding_cost", "YM"),
        ("slow_wire_length", "WE"),
        ("mid_wire_length", "WZ"),
        ("fast_wire_length", "WC"),
        ("edm_time", "EDM"),
        ("engraving_cost", "DK")
    ]
    
    # 构建查询字段列表
    field_names = [field[0] for field in process_fields]
    field_list = ", ".join(field_names)
    
    # 查询所有零件的工艺字段值
    query_sql = f"""
        SELECT s.subgraph_id, {field_list}, f.heat_treatment
        FROM subgraphs s
        LEFT JOIN features f
            ON s.job_id = f.job_id AND s.subgraph_id = f.subgraph_id
        WHERE s.job_id = $1::uuid AND s.subgraph_id = ANY($2::text[])
    """
    
    try:
        rows = await db.fetch_all(query_sql, job_id, subgraph_ids)
        
        # 为每个零件生成工艺描述
        update_tasks = []
        for row in rows:
            subgraph_id = row["subgraph_id"]
            
            # 收集有值的工艺
            processes = []
            
            # 1. 判断NC工艺（从nc_time_cost判断）
            nc_time_cost = nc_time_cost_map.get(subgraph_id)
            nc_processes = _determine_nc_processes(nc_time_cost)
            processes.extend(nc_processes)

            # 2. 热处理工艺（补在NC后面）
            heat_treatment_process = _determine_heat_treatment_process(row.get("heat_treatment"))
            if heat_treatment_process:
                processes.append(heat_treatment_process)

            # 3. 其他工艺字段
            for field_name, abbr in process_fields:
                value = row.get(field_name)
                # 判断字段是否有值（不为 None 且不为 0）
                if value is not None and value != 0:
                    processes.append(abbr)
            
            # 添加固定的 QC
            processes.append("QC")
            
            # 生成工艺描述
            process_description = "-".join(processes)
            
            logger.info(f"[{subgraph_id}] process_description: {process_description}")
            
            # 准备更新任务
            update_tasks.append(_update_single_process_description(job_id, subgraph_id, process_description))
        
        # 并发执行所有更新
        if update_tasks:
            await asyncio.gather(*update_tasks)
            logger.info(f"Successfully updated process descriptions for {len(update_tasks)} parts")
    
    except Exception as e:
        logger.error(f"Failed to update process descriptions: {e}")
        raise


def _determine_nc_processes(nc_time_cost: Any) -> List[str]:
    """
    根据 nc_time_cost 判断NC工艺
    
    判断规则：
    - 开粗（S）：code 为 "开粗"
    - 精铣（SS）：code 为 "精铣"、"半精"、"全精"
    - 钻床（Z）：其他所有 code（如 M、T、L、A、D、ZXZ、M1、M-1、ABC 等）
    
    Args:
        nc_time_cost: NC时间成本数据
        
    Returns:
        List[str]: NC工艺列表（按顺序：S、SS、Z）
    """
    if not nc_time_cost:
        return []
    
    # 如果是字符串，解析为JSON
    if isinstance(nc_time_cost, str):
        try:
            import json
            nc_time_cost = json.loads(nc_time_cost)
        except Exception:
            return []
    
    # 获取 nc_details
    nc_details = nc_time_cost.get("nc_details", [])
    if not nc_details:
        return []
    
    # 判断是否有开粗、精铣、钻床
    has_roughing = False  # 开粗 -> S
    has_milling = False   # 精铣 -> SS
    has_drilling = False  # 钻床 -> Z
    
    # 遍历所有面的所有details
    for nc_detail in nc_details:
        details = nc_detail.get("details", [])
        for detail in details:
            code = detail.get("code", "")
            try:
                value = float(detail.get("value", 0))
                if value > 0:
                    if code == "开粗":
                        has_roughing = True
                    elif code in ["精铣", "半精", "全精"]:
                        has_milling = True
                    else:
                        # 其他所有code都归为钻床（M、T、L、A、D、ZXZ等）
                        has_drilling = True
            except (ValueError, TypeError):
                continue
    
    # 按顺序返回NC工艺：S -> SS -> Z
    nc_processes = []
    if has_roughing:
        nc_processes.append("S")
    if has_milling:
        nc_processes.append("SS")
    if has_drilling:
        nc_processes.append("Z")
    
    return nc_processes


def _determine_heat_treatment_process(heat_treatment: Any) -> str | None:
    """
    根据 features.heat_treatment 映射热处理工艺代码。

    映射规则：
    - HRC -> ZKR
    - 调质 -> 调质
    - 激光 -> 激光
    - 深冷 -> 深冷
    """
    if not heat_treatment:
        return None

    heat_treatment_text = str(heat_treatment).strip()
    if not heat_treatment_text:
        return None

    return (
        "ZKR" if "HRC" in heat_treatment_text.upper() else
        "调质" if "调质" in heat_treatment_text else
        "激光" if "激光" in heat_treatment_text else
        "深冷" if "深冷" in heat_treatment_text else
        "淬火" if "淬火" in heat_treatment_text else
        None
    )


async def _update_single_process_description(job_id: str, subgraph_id: str, process_description: str):
    """
    更新单个零件的工艺描述
    
    Args:
        job_id: 任务ID
        subgraph_id: 子图ID
        process_description: 工艺描述
    """
    sql = """
        UPDATE subgraphs
        SET 
            process_description = $3,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    await db.execute(sql, job_id, subgraph_id, process_description)


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
    
    print("price_total.py - 最终总价计算脚本（阶段 7）")
    print("需要配合 search.py (subgraphs_cost_search) 使用")
    print("\n使用方式：")
    print("1. 先执行阶段 1-6 的所有脚本")
    print("2. 执行 search.py 获取成本汇总")
    print("3. 最后调用本脚本计算最终总价并更新 subgraphs 表和 jobs 表")
