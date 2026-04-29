"""
数据清理和校验脚本（阶段 7）
负责人：李志鹏

功能说明：
在所有成本计算完成后、price_total.py 执行前运行，根据物料的实际情况清理不应该存在的计算数据

判断逻辑：
1. has_material_preparation 不为空 -> 只清空材料费和热处理费相关字段（该物料是备料）
2. metadata 为空或 total_length 为 0 -> 清空线割相关字段和计算步骤

执行顺序：
阶段 7: 数据清理和校验 (本脚本) ← 先执行
阶段 8: 最终总价计算 (price_total.py) ← 后执行
"""
from typing import List, Dict, Any
import logging
import asyncio
import json
import re

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "judgment_cleanup",
    "description": "数据清理和校验：根据物料实际情况清理不应该存在的计算数据（在 price_total 之前执行）",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode"
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
    "needs": ["base_itemcode"],
    "depends_on": []  # 在所有成本计算完成后执行，但在 price_total 之前
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    执行数据清理和校验
    
    Args:
        search_data: 检索数据，包含 base_itemcode
        job_id: 任务ID（可选）
        subgraph_ids: 子图ID列表（可选）
        
    Returns:
        Dict: 清理结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Starting judgment cleanup for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    input_parts = base_data.get("parts", [])
    all_parts = await _get_all_job_parts_for_common_output(job_id, input_parts)
    common_output_cleanup_map = _build_common_output_cleanup_map(input_parts, all_parts)

    if common_output_cleanup_map:
        logger.info(
            "Detected common-output cleanup targets: %s",
            list(common_output_cleanup_map.keys())
        )

    # 并发处理每个零件
    tasks = []
    for part in input_parts:
        tasks.append(
            _process_part_judgment(
                job_id,
                part,
                common_output_cleanup_map.get(part.get("subgraph_id"))
            )
        )
    
    results = await asyncio.gather(*tasks)
    
    logger.info(f"Completed judgment cleanup for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _process_part_judgment(
    job_id: str,
    part: Dict,
    common_output_cleanup: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    处理单个零件的判断和清理
    
    Returns:
        Dict: 清理结果
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    has_material_preparation = part.get("has_material_preparation")
    metadata = part.get("metadata")
    
    logger.info(f"Processing judgment for part: {part_name} ({subgraph_id})")
    
    cleanup_actions = []

    if common_output_cleanup:
        cleanup_action = await _cleanup_common_output(
            job_id,
            subgraph_id,
            common_output_cleanup
        )
        if cleanup_action:
            cleanup_actions.append(cleanup_action)
    
    # 判断1：has_material_preparation 不为空
    if has_material_preparation:
        await _cleanup_material_preparation(job_id, subgraph_id, has_material_preparation)
        cleanup_actions.append({
            "type": "material_preparation",
            "reason": f"该物料备料于: {has_material_preparation}",
            "action": "清空材料费和热处理费相关字段"
        })
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "cleanup_actions": cleanup_actions
        }
    
    # 判断2：metadata 线割数据
    # 如果 metadata 为空或 total_length 为 0，清空线割相关字段
    if metadata:
        wire_cleanup = await _cleanup_wire_data(job_id, subgraph_id, metadata)
        if wire_cleanup:
            cleanup_actions.append(wire_cleanup)
    else:
        # metadata 为空，清空线割相关字段
        logger.info(f"metadata is empty for {subgraph_id}, clearing wire fields")
        wire_cleanup = await _clear_wire_fields(job_id, subgraph_id, "metadata为空")
        if wire_cleanup:
            cleanup_actions.append(wire_cleanup)
    

    
    return {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "cleanup_actions": cleanup_actions
    }


async def _get_all_job_parts_for_common_output(job_id: str, fallback_parts: List[Dict]) -> List[Dict]:
    """
    共出判断需要跨物料比较。这里按 job_id 查全量基础字段，避免只传部分 subgraph_ids 时找不到对比物料。
    """
    if not job_id:
        return fallback_parts or []

    sql = """
        SELECT
            s.subgraph_id,
            s.part_name,
            s.part_code,
            f.processing_instructions,
            f.length_mm,
            f.width_mm,
            f.thickness_mm
        FROM subgraphs s
        LEFT JOIN features f
            ON s.job_id = f.job_id AND s.subgraph_id = f.subgraph_id
        WHERE s.job_id = $1::uuid
    """

    try:
        rows = await db.fetch_all(sql, job_id)
        parts = [dict(row) for row in rows]
        if parts:
            return parts
    except Exception as exc:
        logger.warning("Failed to fetch all job parts for common-output judgment: %s", exc)

    return fallback_parts or []


def _build_common_output_cleanup_map(
    input_parts: List[Dict],
    all_parts: List[Dict]
) -> Dict[str, Dict[str, Any]]:
    cleanup_map: Dict[str, Dict[str, Any]] = {}
    all_parts = all_parts or []
    input_subgraph_ids = {part.get("subgraph_id") for part in input_parts or []}

    part_index = _build_part_lookup_index(all_parts)

    for part in all_parts:
        common_targets = _extract_common_output_targets(part.get("processing_instructions"))
        if not common_targets:
            continue

        for target_code in common_targets:
            target_part = part_index.get(_normalize_part_key(target_code))
            if not target_part:
                logger.info(
                    "Common-output target not found: source=%s, target=%s",
                    _part_label(part),
                    target_code
                )
                continue

            smaller_part, larger_part = _select_smaller_area_part(part, target_part)
            if not smaller_part:
                logger.info(
                    "Skip common-output cleanup because area is missing/equal: source=%s, target=%s",
                    _part_label(part),
                    _part_label(target_part)
                )
                continue

            smaller_subgraph_id = smaller_part.get("subgraph_id")
            if smaller_subgraph_id not in input_subgraph_ids:
                continue

            thickness_same = _is_same_thickness(smaller_part, larger_part)
            existing = cleanup_map.get(smaller_subgraph_id)
            if existing and existing.get("clear_grinding"):
                continue

            cleanup_map[smaller_subgraph_id] = {
                "source_subgraph_id": part.get("subgraph_id"),
                "target_subgraph_id": target_part.get("subgraph_id"),
                "smaller_part": _part_label(smaller_part),
                "larger_part": _part_label(larger_part),
                "common_target": target_code,
                "smaller_area": _area_value(smaller_part),
                "larger_area": _area_value(larger_part),
                "smaller_thickness": _to_float(smaller_part.get("thickness_mm")),
                "larger_thickness": _to_float(larger_part.get("thickness_mm")),
                "clear_grinding": thickness_same,
            }

    return cleanup_map


def _build_part_lookup_index(parts: List[Dict]) -> Dict[str, Dict]:
    index = {}
    for part in parts or []:
        aliases = [
            part.get("subgraph_id"),
            part.get("part_code"),
            part.get("part_name"),
        ]
        part_name = str(part.get("part_name") or "")
        if "." in part_name:
            aliases.append(part_name.rsplit(".", 1)[0])

        for alias in aliases:
            key = _normalize_part_key(alias)
            if key and key not in index:
                index[key] = part
    return index


def _normalize_part_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.replace("－", "-")
    text = re.sub(r"\s+", "", text)
    return text


def _flatten_processing_instructions(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, dict):
        return " ".join(_flatten_processing_instructions(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_processing_instructions(item) for item in value)
    return str(value)


def _extract_common_output_targets(processing_instructions: Any) -> List[str]:
    text = _flatten_processing_instructions(processing_instructions)
    if not text:
        return []

    targets = []
    for match in re.finditer(r"与\s*([A-Za-z0-9][A-Za-z0-9_－-]*)\s*共出", text, re.IGNORECASE):
        target = match.group(1).strip().upper().replace("－", "-")
        if target:
            targets.append(target)
    return targets


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _area_value(part: Dict) -> float:
    length = _to_float(part.get("length_mm"))
    width = _to_float(part.get("width_mm"))
    if length <= 0 or width <= 0:
        return 0.0
    return length * width


def _select_smaller_area_part(part_a: Dict, part_b: Dict):
    area_a = _area_value(part_a)
    area_b = _area_value(part_b)
    if area_a <= 0 or area_b <= 0:
        return None, None
    if abs(area_a - area_b) < 0.001:
        return None, None
    if area_a < area_b:
        return part_a, part_b
    return part_b, part_a


def _is_same_thickness(part_a: Dict, part_b: Dict) -> bool:
    thickness_a = _to_float(part_a.get("thickness_mm"))
    thickness_b = _to_float(part_b.get("thickness_mm"))
    if thickness_a <= 0 or thickness_b <= 0:
        return False
    return abs(thickness_a - thickness_b) < 0.001


def _part_label(part: Dict) -> str:
    return str(part.get("part_code") or part.get("part_name") or part.get("subgraph_id") or "")


async def _cleanup_material_preparation(
    job_id: str,
    subgraph_id: str,
    has_material_preparation: str
):
    """
    判断1：清空备料物料的材料费和热处理费相关字段
    """
    logger.info(f"Cleaning up material preparation for {subgraph_id}: {has_material_preparation}")
    
    # 备料件只不再单独计算材料费和热处理费，其它识别、工时和加工费用正常保留。
    subgraphs_sql = """
        UPDATE subgraphs
        SET 
            material_unit_price = NULL,
            material_cost = NULL,
            heat_treatment_unit_price = NULL,
            heat_treatment_cost = NULL,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    # 清空 processing_cost_calculation_details 表的材料费和热处理费，其它明细正常保留。
    details_sql = """
        UPDATE processing_cost_calculation_details
        SET 
            material_additional_cost = NULL,
            material_cost = NULL,
            heat_treatment_cost = NULL,
            heat_additional_cost = NULL
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    try:
        await db.execute(subgraphs_sql, job_id, subgraph_id)
        await db.execute(details_sql, job_id, subgraph_id)
        logger.info(f"Successfully cleaned up material preparation for {subgraph_id}")
    except Exception as e:
        logger.error(f"Failed to cleanup material preparation for {subgraph_id}: {e}")
        raise


async def _cleanup_common_output(
    job_id: str,
    subgraph_id: str,
    common_output_cleanup: Dict[str, Any]
) -> Dict[str, Any]:
    clear_grinding = bool(common_output_cleanup.get("clear_grinding"))
    logger.info(
        "Cleaning up common-output part: subgraph_id=%s, smaller=%s, larger=%s, clear_grinding=%s",
        subgraph_id,
        common_output_cleanup.get("smaller_part"),
        common_output_cleanup.get("larger_part"),
        clear_grinding
    )

    await _clear_material_and_heat_fields(job_id, subgraph_id)
    if clear_grinding:
        await _clear_water_mill_fields(job_id, subgraph_id)

    return {
        "type": "common_output",
        "reason": (
            f"{common_output_cleanup.get('smaller_part')} 与 "
            f"{common_output_cleanup.get('larger_part')} 共出，"
            f"面积较小({common_output_cleanup.get('smaller_area'):.2f} < "
            f"{common_output_cleanup.get('larger_area'):.2f})"
        ),
        "action": (
            "清空材料费、热处理费、磨床相关费用"
            if clear_grinding
            else "清空材料费和热处理费相关字段"
        ),
        "compare": {
            "smaller_thickness": common_output_cleanup.get("smaller_thickness"),
            "larger_thickness": common_output_cleanup.get("larger_thickness"),
            "same_thickness": clear_grinding,
        }
    }


async def _clear_material_and_heat_fields(job_id: str, subgraph_id: str):
    subgraphs_sql = """
        UPDATE subgraphs
        SET
            material_unit_price = NULL,
            material_cost = NULL,
            heat_treatment_unit_price = NULL,
            heat_treatment_cost = NULL,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    details_sql = """
        UPDATE processing_cost_calculation_details
        SET
            material_additional_cost = NULL,
            material_cost = NULL,
            heat_treatment_cost = NULL,
            heat_additional_cost = NULL
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    await db.execute(subgraphs_sql, job_id, subgraph_id)
    await db.execute(details_sql, job_id, subgraph_id)


async def _clear_water_mill_fields(job_id: str, subgraph_id: str):
    subgraphs_sql = """
        UPDATE subgraphs
        SET
            small_grinding_cost = NULL,
            large_grinding_cost = NULL,
            small_grinding_time = NULL,
            large_grinding_time = NULL,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    details_sql = """
        UPDATE processing_cost_calculation_details
        SET
            thread_ends_cost = NULL,
            hanging_table_cost = NULL,
            chamfer_cost = NULL,
            bevel_cost = NULL,
            oil_tank_cost = NULL,
            high_cost = NULL,
            grinding_cost = NULL,
            plate_cost = NULL,
            long_strip_cost = NULL,
            component_cost = NULL,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE COALESCE(elem->>'category', '') NOT IN (
                    'water_mill_thread_ends',
                    'water_mill_hanging_table',
                    'water_mill_chamfer',
                    'water_mill_bevel',
                    'water_mill_oil_tank',
                    'water_mill_high',
                    'water_mill_grinding',
                    'water_mill_plate',
                    'water_mill_long_strip',
                    'water_mill_component',
                    'water_mill_total_small',
                    'water_mill_total_large'
                )
            )
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    await db.execute(subgraphs_sql, job_id, subgraph_id)
    await db.execute(details_sql, job_id, subgraph_id)


async def _cleanup_wire_data(
    job_id: str,
    subgraph_id: str,
    metadata: Any
) -> Dict[str, Any]:
    """
    判断2：检查并清空线割相关数据
    """
    # 解析 metadata
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception as e:
            logger.warning(f"Failed to parse metadata for {subgraph_id}: {e}")
            return None
    
    # 检查 wire_cut_details
    if not metadata or "wire_cut_details" not in metadata:
        return await _clear_wire_fields(job_id, subgraph_id, "metadata为空或缺少wire_cut_details")
    
    wire_cut_details = metadata["wire_cut_details"]
    
    # 检查是否所有 total_length 都为 0
    has_valid_length = False
    for detail in wire_cut_details:
        total_length = detail.get("total_length", 0)
        # 将 total_length 转换为数字（可能是字符串）
        try:
            length_num = float(total_length) if total_length else 0
        except (ValueError, TypeError):
            length_num = 0
        
        if length_num > 0:
            has_valid_length = True
            break
    
    if not has_valid_length:
        return await _clear_wire_fields(job_id, subgraph_id, "所有wire_cut_details的total_length都为0")
    
    return None


async def _clear_wire_fields(
    job_id: str,
    subgraph_id: str,
    reason: str
) -> Dict[str, Any]:
    """
    清空线割相关字段
    """
    logger.info(f"Clearing wire fields for {subgraph_id}: {reason}")
    
    # 清空 subgraphs 表的线割字段（包含 slow_wire_side_length 和 slow_wire_side_cost）
    subgraphs_sql = """
        UPDATE subgraphs
        SET 
            slow_wire_length = NULL,
            slow_wire_side_length = NULL,
            mid_wire_length = NULL,
            fast_wire_length = NULL,
            slow_wire_cost = NULL,
            slow_wire_side_cost = NULL,
            mid_wire_cost = NULL,
            fast_wire_cost = NULL,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    # 删除 calculation_steps 中的线割相关步骤
    # 删除 category 为 wire_base, wire_speci, wire_special, wire_standard, wire_total 的步骤
    details_sql = """
        UPDATE processing_cost_calculation_details
        SET 
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' NOT IN ('wire_base', 'wire_speci', 'wire_special', 'wire_standard', 'wire_total')
            )
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    try:
        await db.execute(subgraphs_sql, job_id, subgraph_id)
        await db.execute(details_sql, job_id, subgraph_id)
        logger.info(f"Successfully cleared wire fields for {subgraph_id}")
        
        return {
            "type": "wire_data",
            "reason": reason,
            "action": "清空线割相关字段和计算步骤"
        }
    except Exception as e:
        logger.error(f"Failed to clear wire fields for {subgraph_id}: {e}")
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
    
    print("judgment.py - 数据清理和校验脚本")
    print("需要配合 base_itemcode_search.py 使用")
    print("\n使用方式：")
    print("1. 先执行 base_itemcode_search.py 获取零件信息")
    print("2. 调用本脚本进行数据清理和校验")

