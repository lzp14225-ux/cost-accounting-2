"""
数据清理和校验脚本（阶段 7）
负责人：李志鹏

功能说明：
在所有成本计算完成后、price_total.py 执行前运行，根据物料的实际情况清理不应该存在的计算数据

判断逻辑：
1. has_material_preparation 不为空 -> 清空所有成本相关字段（该物料是备料）
2. metadata 为空或 total_length 为 0 -> 清空线割相关字段和计算步骤

执行顺序：
阶段 7: 数据清理和校验 (本脚本) ← 先执行
阶段 8: 最终总价计算 (price_total.py) ← 后执行
"""
from typing import List, Dict, Any
import logging
import asyncio
import json

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
    
    # 并发处理每个零件
    tasks = []
    for part in base_data["parts"]:
        tasks.append(_process_part_judgment(job_id, part))
    
    results = await asyncio.gather(*tasks)
    
    logger.info(f"Completed judgment cleanup for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _process_part_judgment(job_id: str, part: Dict) -> Dict[str, Any]:
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
    
    # 判断1：has_material_preparation 不为空
    if has_material_preparation:
        await _cleanup_material_preparation(job_id, subgraph_id, has_material_preparation)
        cleanup_actions.append({
            "type": "material_preparation",
            "reason": f"该物料备料于: {has_material_preparation}",
            "action": "清空所有成本相关字段"
        })
    
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


async def _cleanup_material_preparation(
    job_id: str,
    subgraph_id: str,
    has_material_preparation: str
):
    """
    判断1：清空备料物料的所有成本相关字段
    """
    logger.info(f"Cleaning up material preparation for {subgraph_id}: {has_material_preparation}")
    
    # 备料件导出时只保留：零件名称、编号、异常情况、其它（备料于）、
    # 小磨工时/费用，以及 NC 相关工时/费用
    # 因此这里把 subgraphs / features / processing_cost_calculation_details 中
    # 与其他导出列相关的字段统一清空。
    subgraphs_sql = """
        UPDATE subgraphs
        SET 
            weight_kg = NULL,
            material_unit_price = NULL,
            material_cost = NULL,
            heat_treatment_unit_price = NULL,
            heat_treatment_cost = NULL,
            process_description = NULL,
            large_grinding_time = NULL,
            milling_machine_time = NULL,
            edm_time = NULL,
            engraving_time = NULL,
            slow_wire_length = NULL,
            slow_wire_side_length = NULL,
            mid_wire_length = NULL,
            fast_wire_length = NULL,
            wire_time = NULL,
            separate_item = NULL,
            total_cost = NULL,
            wire_process_note = NULL,
            milling_machine_cost = NULL,
            slow_wire_cost = NULL,
            slow_wire_side_cost = NULL,
            mid_wire_cost = NULL,
            fast_wire_cost = NULL,
            edm_cost = NULL,
            engraving_cost = NULL,
            large_grinding_cost = NULL,
            separate_item_cost = NULL,
            processing_cost_total = NULL,
            applied_snapshot_ids = NULL,
            rule_reason = NULL,
            override_by_user = false,
            cost_calculation_method = NULL,
            has_sheet_line = false,
            sheet_area_mm2 = NULL,
            sheet_perimeter_mm = NULL,
            sheet_line_data = NULL,
            has_single_nc_calc = false,
            single_prt_file = NULL,
            process_changed = false,
            original_process = NULL,
            prt_3d_file = NULL,
            recalc_count = 0,
            last_recalc_at = NULL,
            last_recalc_by = NULL,
            status = 'pending',
            metadata = NULL,
            wire_process = NULL,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """

    features_sql = """
        UPDATE features
        SET
            length_mm = NULL,
            width_mm = NULL,
            thickness_mm = NULL,
            material = NULL,
            heat_treatment = NULL,
            volume_mm3 = NULL,
            calculated_weight_kg = NULL,
            top_view_wire_length = NULL,
            front_view_wire_length = NULL,
            side_view_wire_length = NULL,
            has_auto_material = false,
            needs_heat_treatment = false,
            boring_length_mm = NULL,
            nc_time_cost = NULL,
            processing_instructions = NULL,
            is_complete = false,
            missing_params = NULL,
            created_by = NULL,
            metadata = NULL
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    # 清空 processing_cost_calculation_details 表的费用/工时明细，只保留备料说明
    details_sql = """
        UPDATE processing_cost_calculation_details
        SET 
            process_type = NULL,
            adjusted_thickness = NULL,
            weight = NULL,
            multiplier_coefficient = NULL,
            standard_hours = NULL,
            actual_hours = NULL,
            basic_processing_cost = NULL,
            special_base_cost = NULL,
            standard_base_cost = NULL,
            selected_base_cost = NULL,
            base_cost_selection = NULL,
            material_additional_cost = NULL,
            material_cost = NULL,
            heat_treatment_cost = NULL,
            heat_additional_cost = NULL,
            additional_cost_total = NULL,
            final_cost = NULL,
            weight_price_steps = NULL,
            calculation_steps = jsonb_build_array(
                jsonb_build_object(
                    'category', 'material_preparation',
                    'steps', jsonb_build_array(
                        jsonb_build_object(
                            'step', '备料说明',
                            'note', $3::text
                        )
                    )
                )
            )
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    try:
        await db.execute(subgraphs_sql, job_id, subgraph_id)
        await db.execute(features_sql, job_id, subgraph_id)
        await db.execute(details_sql, job_id, subgraph_id, f"该物料备料于: {has_material_preparation}")
        logger.info(f"Successfully cleaned up material preparation for {subgraph_id}")
    except Exception as e:
        logger.error(f"Failed to cleanup material preparation for {subgraph_id}: {e}")
        raise


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

