"""
NC时间计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息
   - nc_time_cost
   - process_description
   - length_mm / width_mm / thickness_mm
2. 调用 nc_search 获取 NC 工时配置
   - nc_base：基础工时（模板/零件）
   - nc_template_clamp / nc_component_clamp：装夹工时（模板/零件）
   - nc_daobu：带“开加刀补/刀补”关键词的程序时间倍数
   - nc_drilling：钻孔/钻床时间倍数
   - nc_hole：满足条件的镗/铰/搪孔按“分钟/孔”替换计算
   - side_hole：模座侧孔按“分钟/孔”替换计算
3. 调用 wire_base_search 获取模板/零件判断阈值
4. 检查 nc_time_cost 是否为空，为空则跳过计算返回 0
5. 如果 process_description 为空，按原逻辑计算：
   - 按 face_code 分组
   - 分类统计：精铣（精铣、半精、全精）、开粗（开粗）、钻孔/钻床（其他所有 code）
   - 带“开加刀补/刀补”的明细先乘 nc_daobu 倍数
   - 钻孔/钻床分类汇总后再乘 nc_drilling 倍数
   - 满足 nc_hole 条件的镗/铰/搪孔，不再取 nc_time_cost 的原始时间，改按“分钟/孔”计算
   - 模座的 C/C_B/Z_VIEW/B_VIEW 面侧孔，不再取 nc_time_cost 的原始时间，改按 side_hole 的“分钟/孔”计算
   - 将该 face_code 下的所有 value 相加后从分钟转换为小时
6. 如果 process_description 不为空，按工艺分段计算：
   - 先根据尺寸和 wire_base 阈值判断模板/零件
   - 动态获取对应的基础工时和装夹工时
   - 从 process_description 中识别“钻孔 / CNC开粗 / CNC精铣”
   - 连续出现的上述工艺视为同一段；中间被其他工艺打断则重新起一段
   - 对每个 face_code 的每一段计算：
     max(该段相关 NC 时间 + 装夹工时, 基础工时)
   - 该 face_code 的最终时间 = 各段结果之和
7. 更新 processing_cost_calculation_details 表的对应字段：
   - Z -> nc_z_cost
   - B -> nc_b_cost
   - C -> nc_c_cost
   - C_B -> nc_c_b_cost
   - Z_VIEW -> nc_z_view_cost
   - B_VIEW -> nc_b_view_cost
"""
from typing import List, Dict, Any, Tuple
import logging
import asyncio
import re

from ._batch_update_helper import batch_upsert_with_steps
from .price_nc_base import _build_nc_base_config, _get_template_threshold, _determine_part_type

logger = logging.getLogger(__name__)

# face_code 到数据库字段的映射
FACE_CODE_TO_FIELD = {
    "Z": "nc_z_cost",
    "B": "nc_b_cost",
    "C": "nc_c_cost",
    "C_B": "nc_c_b_cost",
    "Z_VIEW": "nc_z_view_cost",
    "B_VIEW": "nc_b_view_cost"
}

# NC 明细分类
DETAIL_CATEGORY_LABELS = {
    "roughing": "开粗",
    "milling": "精铣",
    "drilling": "钻孔/钻床"
}

# 工艺说明中的 NC 工艺映射
PROCESS_TYPE_LABELS = {
    "roughing": "CNC开粗",
    "milling": "CNC精铣",
    "drilling": "钻孔"
}

SIDE_HOLE_FACE_CODES = {"C", "C_B", "Z_VIEW", "B_VIEW"}

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_nc_time_cost",
    "description": "计算NC时间：根据工艺说明按段汇总各面的NC时间；若无工艺说明则回退到原始汇总逻辑",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode、nc 和 wire_base"
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
    "needs": ["base_itemcode", "nc", "wire_base"]
}


def _filter_steps_by_face(calculation_steps: List[Dict], face_code: str) -> List[Dict]:
    """
    过滤计算步骤，只保留指定 face_code 的步骤和汇总步骤
    
    Args:
        calculation_steps: 完整的计算步骤列表
        face_code: 要保留的 face_code（如 "Z", "B", "C" 等）
        
    Returns:
        List[Dict]: 过滤后的计算步骤
    """
    filtered_steps = []
    
    for step in calculation_steps:
        step_name = step.get("step", "")
        step_face_code = step.get("face_code", "")

        # 保留指定 face_code 的计算步骤
        if step_face_code == face_code:
            filtered_steps.append(step)
        # 保留通用步骤
        elif step.get("common_step"):
            filtered_steps.append(step)
        # 保留汇总步骤（没有 face_code 字段）
        elif "汇总" in step_name or "检查" in step_name or "解析" in step_name:
            filtered_steps.append(step)

    return filtered_steps


def _build_nc_time_config(nc_prices: List[Dict]) -> Dict[str, Any]:
    """
    构建 NC 时间配置

    Returns:
        {
            "nc_base_hours": {
                "template": 1.0,
                "component": 0.5
            },
            "clamp_hours": {
                "template": 0.5,
                "component": 0.2
            },
            "daobu_multiplier": 5.0,
            "drilling_multiplier": 2.0,
            "hole_rule": {
                "minutes_per_hole": 15.0,
                "min_diameter": 17.0
            },
            "side_hole_minutes_per_hole": 20.0
        }
    """
    nc_base_config = _build_nc_base_config(nc_prices)
    clamp_hours = {}
    daobu_multiplier = 1.0
    drilling_multiplier = 1.0
    hole_rule = {
        "minutes_per_hole": 0.0,
        "min_diameter": 0.0
    }
    side_hole_minutes_per_hole = 0.0

    for item in nc_prices:
        sub_category = item.get("sub_category")
        price = item.get("price", 0)

        try:
            hours = float(price)
        except (ValueError, TypeError):
            logger.warning(f"Invalid clamp price for sub_category={sub_category}: {price}")
            continue

        if sub_category == "nc_template_clamp":
            clamp_hours["template"] = hours
        elif sub_category == "nc_component_clamp":
            clamp_hours["component"] = hours
        elif sub_category == "nc_daobu":
            daobu_multiplier = hours
        elif sub_category == "nc_drilling":
            drilling_multiplier = hours
        elif sub_category == "nc_hole":
            try:
                min_diameter = float(str(item.get("min_num") or 0).strip())
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid nc_hole min_num: %s, defaulting to 0",
                    item.get("min_num")
                )
                min_diameter = 0.0
            hole_rule = {
                "minutes_per_hole": hours,
                "min_diameter": min_diameter
            }
        elif sub_category == "side_hole":
            side_hole_minutes_per_hole = hours

    config = {
        "nc_base_hours": nc_base_config.get("nc_base_hours", {}),
        "clamp_hours": clamp_hours,
        "daobu_multiplier": daobu_multiplier,
        "drilling_multiplier": drilling_multiplier,
        "hole_rule": hole_rule,
        "side_hole_minutes_per_hole": side_hole_minutes_per_hole
    }

    logger.info(
        "NC time config built: nc_base_hours=%s, clamp_hours=%s, daobu_multiplier=%s, drilling_multiplier=%s, hole_rule=%s, side_hole_minutes_per_hole=%s",
        config["nc_base_hours"],
        config["clamp_hours"],
        config["daobu_multiplier"],
        config["drilling_multiplier"],
        config["hole_rule"],
        config["side_hole_minutes_per_hole"]
    )
    return config


def _classify_detail_code(code: str) -> str:
    """将 nc_details 中的 code 归类为 开粗 / 精铣 / 钻孔(钻床)。"""
    if code in ["精铣", "半精", "全精"]:
        return "milling"
    if code == "开粗":
        return "roughing"
    return "drilling"


def _identify_process_type(process_name: str) -> str:
    """识别 process_description 中的 NC 相关工艺类型。"""
    normalized = str(process_name or "").replace(" ", "")

    if "钻孔" in normalized:
        return "drilling"
    if "CNC开粗" in normalized or normalized.startswith("开粗"):
        return "roughing"
    if "CNC精铣" in normalized or normalized.endswith("精铣"):
        return "milling"

    return ""


def _build_nc_process_groups(process_description: str) -> List[Dict[str, Any]]:
    """
    从工艺说明中识别连续的 NC 工艺段。

    连续出现的“钻孔 / CNC开粗 / CNC精铣”归为同一段；
    中间遇到其他工艺，则重新起一段。
    """
    if not process_description or not str(process_description).strip():
        return []

    raw_text = str(process_description).strip().strip('"').strip("'")
    process_items = [
        item.strip()
        for item in re.split(r"\s*(?:->|→)\s*", raw_text)
        if item and item.strip()
    ]

    groups = []
    current_group = []

    for item in process_items:
        process_type = _identify_process_type(item)
        if process_type:
            current_group.append({
                "raw": item,
                "process_type": process_type
            })
            continue

        if current_group:
            groups.append(_finalize_process_group(current_group))
            current_group = []

    if current_group:
        groups.append(_finalize_process_group(current_group))

    return groups


def _finalize_process_group(group_items: List[Dict[str, str]]) -> Dict[str, Any]:
    """将连续的工艺项整理为一个工艺段。"""
    process_types = []
    for item in group_items:
        process_type = item["process_type"]
        if process_type not in process_types:
            process_types.append(process_type)

    return {
        "process_types": process_types,
        "process_names": [item["raw"] for item in group_items],
        "raw_sequence": " -> ".join(item["raw"] for item in group_items)
    }


def _summarize_face_details(details: List[Dict[str, Any]]) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """
    汇总单个面的明细。

    Returns:
        (
            {"roughing": 分钟, "milling": 分钟, "drilling": 分钟},
            detail_breakdown
        )
    """
    category_minutes = {
        "roughing": 0.0,
        "milling": 0.0,
        "drilling": 0.0
    }
    detail_breakdown = []

    for detail in details:
        code = detail.get("code", "")
        value = detail.get("value", 0)

        try:
            value_float = float(value)
        except (ValueError, TypeError):
            logger.warning(f"Invalid value for code {code}: {value}, skipping")
            continue

        category = _classify_detail_code(code)
        category_minutes[category] += value_float

        detail_breakdown.append({
            "code": code,
            "value_minutes": round(value_float, 2),
            "category": DETAIL_CATEGORY_LABELS[category]
        })

    return category_minutes, detail_breakdown


def _normalize_processing_instructions(processing_instructions: Any) -> Dict[str, List[str]]:
    """将 processing_instructions 规范化为 {frame: [line, ...]} 结构。"""
    if not processing_instructions:
        return {}

    if isinstance(processing_instructions, dict):
        normalized = {}
        for key, value in processing_instructions.items():
            if isinstance(value, list):
                normalized[key] = [str(item) for item in value if str(item).strip()]
            elif value is not None:
                normalized[key] = [str(value)]
        return normalized

    if isinstance(processing_instructions, str):
        try:
            import json
            parsed = json.loads(processing_instructions)
            return _normalize_processing_instructions(parsed)
        except Exception:
            text = processing_instructions.strip()
            return {"frame_1": [text]} if text else {}

    return {}


def _extract_instruction_operation_map(processing_instructions: Any) -> Dict[str, Dict[str, Any]]:
    """从加工说明中按工序号提取孔数和原始行。"""
    normalized = _normalize_processing_instructions(processing_instructions)
    operations = {}

    for frame_name, lines in normalized.items():
        for raw_line in lines:
            line = str(raw_line or "").strip()
            if not line:
                continue

            code_match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*:", line)
            count_match = re.match(r"^\s*[A-Za-z][A-Za-z0-9_]*\s*:\s*(\d+)", line)
            if not code_match or not count_match:
                continue

            code = code_match.group(1).strip()
            operations[code] = {
                "code": code,
                "hole_count": int(count_match.group(1)),
                "frame": frame_name,
                "source_line": line
            }

    return operations


def _extract_special_hole_replacements(
    processing_instructions: Any,
    hole_rule: Dict[str, float]
) -> Dict[str, Dict[str, Any]]:
    """
    从加工说明中提取需要按 nc_hole 规则替换计算的孔工序。

    规则：
    - 模糊匹配“镗 / 铰 / 搪”
    - 直径 >= hole_rule.min_diameter
    - 提取工序 code（如 L5 / C1）和孔数
    """
    minutes_per_hole = float(hole_rule.get("minutes_per_hole", 0) or 0)
    min_diameter = float(hole_rule.get("min_diameter", 0) or 0)

    if minutes_per_hole <= 0:
        return {}

    normalized = _normalize_processing_instructions(processing_instructions)
    replacements = {}

    for frame_name, lines in normalized.items():
        for raw_line in lines:
            line = str(raw_line or "").strip()
            if not line:
                continue

            if not any(keyword in line for keyword in ["镗", "铰", "搪"]):
                continue

            code_match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*:", line)
            count_match = re.match(r"^\s*[A-Za-z][A-Za-z0-9_]*\s*:\s*(\d+)", line)
            diameter_match = re.search(r"[Φφ]\s*(\d+(?:\.\d+)?)", line)

            if not code_match or not count_match or not diameter_match:
                continue

            code = code_match.group(1).strip()
            hole_count = int(count_match.group(1))
            diameter = float(diameter_match.group(1))

            if diameter < min_diameter:
                continue

            replacement_minutes = round(hole_count * minutes_per_hole, 2)
            replacements[code] = {
                "code": code,
                "hole_count": hole_count,
                "diameter": round(diameter, 2),
                "minutes_per_hole": round(minutes_per_hole, 2),
                "replacement_minutes": replacement_minutes,
                "frame": frame_name,
                "source_line": line
            }

    return replacements


def _extract_side_hole_replacements(
    part_name: str,
    processing_instructions: Any,
    minutes_per_hole: float
) -> Dict[str, Dict[str, Any]]:
    """
    提取模座侧孔替换规则。

    规则：
    - part_name 模糊匹配“模座”
    - 加工说明中存在同名工序号
    - 该工序说明包含“钻”
    """
    if "模座" not in str(part_name or ""):
        return {}

    minutes = float(minutes_per_hole or 0)
    if minutes <= 0:
        return {}

    replacements = {}
    for code, operation in _extract_instruction_operation_map(processing_instructions).items():
        source_line = operation.get("source_line", "")
        if "钻" not in source_line:
            continue

        replacement_minutes = round(operation["hole_count"] * minutes, 2)
        replacements[code] = {
            "code": code,
            "hole_count": operation["hole_count"],
            "minutes_per_hole": round(minutes, 2),
            "replacement_minutes": replacement_minutes,
            "frame": operation.get("frame"),
            "source_line": source_line
        }

    return replacements


def _apply_detail_adjustments(
    detail: Dict[str, Any],
    nc_time_config: Dict[str, Any]
) -> Tuple[float, List[str]]:
    """对单条 nc_detail 应用刀补等明细级规则。"""
    value = detail.get("value", 0)
    code = detail.get("code", "")
    program_name = str(detail.get("program_name") or "")

    try:
        adjusted_value = float(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid value for code {code}: {value}, skipping")
        raise

    notes = []
    daobu_multiplier = float(nc_time_config.get("daobu_multiplier", 1) or 1)

    if "刀补" in program_name and daobu_multiplier != 1:
        adjusted_value *= daobu_multiplier
        notes.append(f"program_name含刀补关键词，时间 x{round(daobu_multiplier, 2)}")

    return adjusted_value, notes


def _summarize_face_details_with_rules(
    details: List[Dict[str, Any]],
    face_code: str,
    nc_time_config: Dict[str, Any],
    special_hole_replacements: Dict[str, Dict[str, Any]],
    side_hole_replacements: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, float], List[Dict[str, Any]], Dict[str, Any]]:
    """
    汇总单个面的明细，并应用：
    - 刀补倍率
    - 钻孔倍率
    - 特殊孔替换规则
    - 模座侧孔替换规则
    """
    category_minutes = {
        "roughing": 0.0,
        "milling": 0.0,
        "drilling": 0.0
    }
    detail_breakdown = []
    matched_special_codes = set()
    matched_side_hole_codes = set()
    skipped_details = []

    for detail in details:
        code = detail.get("code", "")
        category = _classify_detail_code(code)

        if (
            face_code in SIDE_HOLE_FACE_CODES
            and category == "drilling"
            and code in side_hole_replacements
        ):
            matched_side_hole_codes.add(code)
            skipped_details.append({
                "code": code,
                "program_name": detail.get("program_name"),
                "reason": "模座侧孔命中side_hole规则，原始nc_time_cost时间不计，改按分钟/孔替换"
            })
            continue

        if code in special_hole_replacements:
            matched_special_codes.add(code)
            skipped_details.append({
                "code": code,
                "program_name": detail.get("program_name"),
                "reason": "该工序命中nc_hole规则，原始nc_time_cost时间不计，改按分钟/孔替换"
            })
            continue

        try:
            adjusted_value, adjustment_notes = _apply_detail_adjustments(detail, nc_time_config)
        except (ValueError, TypeError):
            continue

        category_minutes[category] += adjusted_value

        detail_breakdown.append({
            "code": code,
            "original_value_minutes": round(float(detail.get("value", 0)), 2),
            "adjusted_value_minutes": round(adjusted_value, 2),
            "category": DETAIL_CATEGORY_LABELS[category],
            "program_name": detail.get("program_name"),
            "adjustments": adjustment_notes
        })

    replacement_minutes = 0.0
    replacement_items = []
    for code in sorted(matched_special_codes):
        replacement_info = special_hole_replacements[code]
        replacement_minutes += replacement_info["replacement_minutes"]
        replacement_items.append(replacement_info)

    side_hole_replacement_minutes = 0.0
    side_hole_replacement_items = []
    for code in sorted(matched_side_hole_codes):
        replacement_info = side_hole_replacements[code]
        side_hole_replacement_minutes += replacement_info["replacement_minutes"]
        side_hole_replacement_items.append(replacement_info)

    drilling_minutes_before_multiplier = category_minutes["drilling"]
    drilling_multiplier = float(nc_time_config.get("drilling_multiplier", 1) or 1)
    if drilling_multiplier != 1 and category_minutes["drilling"] > 0:
        category_minutes["drilling"] *= drilling_multiplier

    drilling_minutes_after_multiplier_before_replacements = category_minutes["drilling"]
    if replacement_minutes > 0:
        category_minutes["drilling"] += replacement_minutes
    if side_hole_replacement_minutes > 0:
        category_minutes["drilling"] += side_hole_replacement_minutes

    face_rule_summary = {
        "face_code": face_code,
        "matched_special_hole_codes": sorted(matched_special_codes),
        "special_hole_replacements": replacement_items,
        "matched_side_hole_codes": sorted(matched_side_hole_codes),
        "side_hole_replacements": side_hole_replacement_items,
        "skipped_original_details": skipped_details,
        "drilling_minutes_before_multiplier": round(drilling_minutes_before_multiplier, 2),
        "drilling_multiplier": round(drilling_multiplier, 2),
        "drilling_minutes_after_multiplier_before_replacements": round(drilling_minutes_after_multiplier_before_replacements, 2),
        "special_hole_replacement_minutes": round(replacement_minutes, 2),
        "side_hole_replacement_minutes": round(side_hole_replacement_minutes, 2),
        "drilling_minutes_after_multiplier": round(category_minutes["drilling"], 2)
    }

    return category_minutes, detail_breakdown, face_rule_summary


def _calculate_face_time_legacy(
    face_code: str,
    category_minutes: Dict[str, float],
    detail_breakdown: List[Dict[str, Any]]
) -> Tuple[float, Dict[str, Any]]:
    """process_description 为空时，沿用旧的按分钟汇总逻辑。"""
    roughing_minutes = category_minutes["roughing"]
    milling_minutes = category_minutes["milling"]
    drilling_minutes = category_minutes["drilling"]

    total_minutes = roughing_minutes + milling_minutes + drilling_minutes
    total_hours = round(total_minutes / 60.0, 2)

    if total_minutes > 0:
        step = {
            "step": f"按原逻辑计算 {face_code} 面",
            "face_code": face_code,
            "details": detail_breakdown,
            "summary": {
                "开粗_minutes": round(roughing_minutes, 2),
                "精铣_minutes": round(milling_minutes, 2),
                "钻孔_钻床_minutes": round(drilling_minutes, 2)
            },
            "total_minutes": round(total_minutes, 2),
            "formula": (
                f"({round(roughing_minutes, 2)} + {round(milling_minutes, 2)} + "
                f"{round(drilling_minutes, 2)}) / 60 = {total_hours}"
            ),
            "total_hours": total_hours,
            "note": "process_description为空或未识别到相关工艺，按旧逻辑直接汇总分钟并转换为小时"
        }
    else:
        step = {
            "step": f"按原逻辑计算 {face_code} 面",
            "face_code": face_code,
            "note": "该面总值为0"
        }

    return total_hours, step


def _calculate_face_time_by_process(
    face_code: str,
    category_minutes: Dict[str, float],
    detail_breakdown: List[Dict[str, Any]],
    process_groups: List[Dict[str, Any]],
    nc_base_hours: float,
    clamp_hours: float
) -> Tuple[float, Dict[str, Any]]:
    """按工艺段计算单个面的 NC 时间。"""
    category_hours = {
        key: value / 60.0
        for key, value in category_minutes.items()
    }

    group_results = []
    face_total_hours = 0.0

    for index, group in enumerate(process_groups, start=1):
        included_items = []
        raw_processing_hours = 0.0

        for process_type in group["process_types"]:
            current_hours = category_hours.get(process_type, 0.0)
            if current_hours <= 0:
                continue

            included_items.append({
                "process_type": process_type,
                "process_name": PROCESS_TYPE_LABELS[process_type],
                "hours": round(current_hours, 2)
            })
            raw_processing_hours += current_hours

        if raw_processing_hours <= 0:
            group_results.append({
                "group_index": index,
                "group_sequence": group["raw_sequence"],
                "group_processes": [PROCESS_TYPE_LABELS[t] for t in group["process_types"]],
                "included_items": [],
                "note": "该面在这一连续工艺段没有可计入的NC时间，跳过"
            })
            continue

        combined_hours = raw_processing_hours + clamp_hours
        final_hours = max(combined_hours, nc_base_hours)
        face_total_hours += final_hours

        item_text = " + ".join(
            f"{item['process_name']}{item['hours']}"
            for item in included_items
        )

        group_results.append({
            "group_index": index,
            "group_sequence": group["raw_sequence"],
            "group_processes": [PROCESS_TYPE_LABELS[t] for t in group["process_types"]],
            "included_items": included_items,
            "raw_processing_hours": round(raw_processing_hours, 2),
            "clamp_hours": round(clamp_hours, 2),
            "combined_hours_before_base": round(combined_hours, 2),
            "nc_base_hours": round(nc_base_hours, 2),
            "final_hours": round(final_hours, 2),
            "formula": (
                f"max(({item_text}) + 装夹{round(clamp_hours, 2)}, "
                f"基础工时{round(nc_base_hours, 2)}) = {round(final_hours, 2)}"
            ),
            "note": "同一连续工艺段只计一次装夹工时，再与基础工时比较取最大值"
        })

    if face_total_hours > 0:
        step = {
            "step": f"按工艺分段计算 {face_code} 面",
            "face_code": face_code,
            "details": detail_breakdown,
            "summary_hours": {
                "开粗": round(category_hours["roughing"], 2),
                "精铣": round(category_hours["milling"], 2),
                "钻孔_钻床": round(category_hours["drilling"], 2)
            },
            "process_groups": group_results,
            "total_hours": round(face_total_hours, 2),
            "note": "连续的钻孔/CNC开粗/CNC精铣合并计算；被其他工艺打断后重新计装夹和基础工时"
        }
    else:
        step = {
            "step": f"按工艺分段计算 {face_code} 面",
            "face_code": face_code,
            "process_groups": group_results,
            "note": "该面在所有连续NC工艺段中的有效时间都为0"
        }

    return round(face_total_hours, 2), step


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算NC时间

    Args:
        search_data: 检索数据，包含 base_itemcode、nc 和 wire_base
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）

    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    nc_data = search_data["nc"]
    wire_base_data = search_data["wire_base"]

    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")

    logger.info(f"Calculating NC time for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")

    # 构建 NC 时间配置
    nc_time_config = _build_nc_time_config(nc_data.get("nc_prices", []))
    template_threshold = _get_template_threshold(wire_base_data.get("rule_prices", []))

    # Step 1: 计算每个零件的NC时间
    results = []
    db_updates = []

    for part in base_data["parts"]:
        result, db_data = await _calculate_part_nc_time_cost(
            job_id,
            part,
            nc_time_config,
            template_threshold
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # Step 2: 批量写入数据库（按 face_code 分别更新对应字段）
    if db_updates:
        for face_code, field_name in FACE_CODE_TO_FIELD.items():
            updates = [
                {
                    "job_id": d["job_id"],
                    "subgraph_id": d["subgraph_id"],
                    "value": d["face_costs"].get(face_code, 0),
                    "steps": _filter_steps_by_face(d["calculation_steps"], face_code)
                }
                for d in db_updates
            ]
            await batch_upsert_with_steps(updates, f"nc_{face_code.lower()}", field_name)
    
    logger.info(f"Completed NC time calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _calculate_part_nc_time_cost(
    job_id: str,
    part: Dict,
    nc_time_config: Dict[str, Any],
    template_threshold: float
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的NC时间

    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    nc_time_cost_data = part.get("nc_time_cost")
    process_description = str(part.get("process_description") or "").strip()
    processing_instructions = part.get("processing_instructions")

    logger.info(f"Calculating NC time for part: {part_name} ({subgraph_id})")

    # 检查 nc_time_cost 数据
    if not nc_time_cost_data:
        logger.info(f"No nc_time_cost data for {part_name}, skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "face_costs": {},
            "note": "nc_time_cost数据为空，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "face_costs": {face: 0 for face in FACE_CODE_TO_FIELD.keys()},
            "calculation_steps": [{
                "step": "检查nc_time_cost",
                "common_step": True,
                "note": "nc_time_cost数据为空，跳过NC时间计算"
            }]
        }
    
    # 如果 nc_time_cost_data 是字符串，解析为 JSON
    if isinstance(nc_time_cost_data, str):
        try:
            import json
            nc_time_cost_data = json.loads(nc_time_cost_data)
            logger.info(f"Parsed nc_time_cost from JSON string for {part_name}")
        except Exception as e:
            logger.error(f"Failed to parse nc_time_cost JSON for {part_name}: {e}")
            return {
                "subgraph_id": subgraph_id,
                "part_name": part_name,
                "face_costs": {},
                "note": f"nc_time_cost JSON解析失败: {e}"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "face_costs": {face: 0 for face in FACE_CODE_TO_FIELD.keys()},
                "calculation_steps": [{
                "step": "解析nc_time_cost",
                "common_step": True,
                "note": f"JSON解析失败: {e}，跳过NC时间计算"
            }]
        }
    
    # 获取 nc_details
    nc_details = nc_time_cost_data.get("nc_details", [])
    if not nc_details:
        logger.info(f"No nc_details in nc_time_cost for {part_name}, skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "face_costs": {},
            "note": "nc_details为空，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "face_costs": {face: 0 for face in FACE_CODE_TO_FIELD.keys()},
            "calculation_steps": [{
                "step": "检查nc_details",
                "common_step": True,
                "note": "nc_details为空，跳过NC时间计算"
            }]
        }

    calculation_steps = []
    face_costs = {}  # 存储每个 face_code 的总值
    special_hole_replacements = _extract_special_hole_replacements(
        processing_instructions,
        nc_time_config.get("hole_rule", {})
    )
    side_hole_replacements = _extract_side_hole_replacements(
        part_name,
        processing_instructions,
        nc_time_config.get("side_hole_minutes_per_hole", 0)
    )

    # 解析工艺说明：为空或未识别到相关工艺时回退到原逻辑
    process_groups = _build_nc_process_groups(process_description)
    use_process_group_logic = bool(process_description and process_groups)

    if process_description:
        calculation_steps.append({
            "step": "解析工艺说明",
            "common_step": True,
            "process_description": process_description,
            "recognized_process_groups": [
                {
                    "group_index": idx + 1,
                    "group_sequence": group["raw_sequence"],
                    "group_processes": [PROCESS_TYPE_LABELS[t] for t in group["process_types"]]
                }
                for idx, group in enumerate(process_groups)
            ],
            "note": (
                "已识别连续 NC 工艺段，按段计算"
                if process_groups
                else "未识别到钻孔/CNC开粗/CNC精铣，回退到原逻辑"
            )
        })
    else:
        calculation_steps.append({
            "step": "解析工艺说明",
            "common_step": True,
            "process_description": process_description,
            "note": "process_description为空，回退到原逻辑"
        })

    calculation_steps.append({
        "step": "解析加工说明中的特殊孔规则",
        "common_step": True,
        "processing_instructions_available": bool(processing_instructions),
        "hole_rule": {
            "minutes_per_hole": round(float(nc_time_config.get("hole_rule", {}).get("minutes_per_hole", 0) or 0), 2),
            "min_diameter": round(float(nc_time_config.get("hole_rule", {}).get("min_diameter", 0) or 0), 2)
        },
        "matched_hole_codes": list(special_hole_replacements.keys()),
        "matched_hole_items": list(special_hole_replacements.values()),
        "note": (
            "命中的镗/铰/搪孔将按分钟/孔替换计算，并从nc_time_cost原始明细中移除"
            if special_hole_replacements
            else "未命中需要替换计算的镗/铰/搪孔"
        )
    })

    calculation_steps.append({
        "step": "解析模座侧孔规则",
        "common_step": True,
        "part_name": part_name,
        "is_die_base": "模座" in str(part_name or ""),
        "side_hole_face_codes": sorted(SIDE_HOLE_FACE_CODES),
        "side_hole_minutes_per_hole": round(float(nc_time_config.get("side_hole_minutes_per_hole", 0) or 0), 2),
        "matched_side_hole_codes": list(side_hole_replacements.keys()),
        "matched_side_hole_items": list(side_hole_replacements.values()),
        "note": (
            "模座侧面钻孔工序将按side_hole分钟/孔替换计算，并从nc_time_cost原始明细中移除"
            if side_hole_replacements
            else "未命中模座侧孔替换规则"
        )
    })

    part_type = ""
    nc_base_hours = 0.0
    clamp_hours = 0.0

    if use_process_group_logic:
        length_mm = part["length_mm"]
        width_mm = part["width_mm"]
        thickness_mm = part["thickness_mm"]

        part_type, part_type_desc = _determine_part_type(
            length_mm, width_mm, thickness_mm, template_threshold
        )
        calculation_steps.append({
            "step": "判断模板或零件",
            "common_step": True,
            "dimensions": {
                "length_mm": length_mm,
                "width_mm": width_mm,
                "thickness_mm": thickness_mm
            },
            "template_threshold": template_threshold,
            "part_type": part_type,
            "description": part_type_desc
        })

        nc_base_hours = nc_time_config.get("nc_base_hours", {}).get(part_type)
        clamp_hours = nc_time_config.get("clamp_hours", {}).get(part_type)

        if nc_base_hours is None or clamp_hours is None:
            missing_items = []
            if nc_base_hours is None:
                missing_items.append(f"{part_type} 的 nc_base")
            if clamp_hours is None:
                missing_items.append(f"{part_type} 的 clamp")

            message = f"缺少NC时间配置: {', '.join(missing_items)}"
            logger.warning(f"{message} for part: {part_name} ({subgraph_id})")

            return {
                "subgraph_id": subgraph_id,
                "part_name": part_name,
                "face_costs": {face: 0 for face in FACE_CODE_TO_FIELD.keys()},
                "note": message,
                "calculation_mode": "process_grouped"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "face_costs": {face: 0 for face in FACE_CODE_TO_FIELD.keys()},
                "calculation_steps": calculation_steps + [{
                    "step": "获取NC时间配置",
                    "common_step": True,
                    "part_type": part_type,
                    "note": message
                }]
            }

        calculation_steps.append({
            "step": "获取NC时间配置",
            "common_step": True,
            "part_type": part_type,
            "nc_base_hours": round(nc_base_hours, 2),
            "clamp_hours": round(clamp_hours, 2),
            "daobu_multiplier": round(float(nc_time_config.get("daobu_multiplier", 1) or 1), 2),
            "drilling_multiplier": round(float(nc_time_config.get("drilling_multiplier", 1) or 1), 2),
            "hole_rule": nc_time_config.get("hole_rule", {}),
            "side_hole_minutes_per_hole": round(float(nc_time_config.get("side_hole_minutes_per_hole", 0) or 0), 2),
            "note": "按模板/零件分别动态获取基础工时和装夹工时，并加载刀补倍率/钻孔倍率/特殊孔/模座侧孔替换规则"
        })

    # 按 face_code 分组计算
    for nc_detail in nc_details:
        face_code = nc_detail.get("face_code", "")
        details = nc_detail.get("details", [])

        if not face_code or not details:
            continue

        category_minutes, detail_breakdown, face_rule_summary = _summarize_face_details_with_rules(
            details,
            face_code,
            nc_time_config,
            special_hole_replacements,
            side_hole_replacements
        )

        if use_process_group_logic:
            face_total_hours, step = _calculate_face_time_by_process(
                face_code,
                category_minutes,
                detail_breakdown,
                process_groups,
                nc_base_hours,
                clamp_hours
            )
        else:
            face_total_hours, step = _calculate_face_time_legacy(
                face_code,
                category_minutes,
                detail_breakdown
            )

        step["applied_rules"] = face_rule_summary
        face_costs[face_code] = face_total_hours
        calculation_steps.append(step)

    # 确保所有 face_code 都有值（即使为0）
    for face_code in FACE_CODE_TO_FIELD.keys():
        if face_code not in face_costs:
            face_costs[face_code] = 0
    
    # 添加汇总步骤
    calculation_steps.append({
        "step": "汇总各面NC时间",
        "face_costs": {k: round(v, 2) for k, v in face_costs.items()}
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "face_costs": {k: round(v, 2) for k, v in face_costs.items()},
        "calculation_mode": "process_grouped" if use_process_group_logic else "legacy"
    }

    if part_type:
        result["part_type"] = part_type

    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "face_costs": face_costs,
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
        print("Usage: python price_nc_time.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用检索脚本获取数据
    print("请通过 MCP 服务或 API 调用此计算脚本")
    print(f"job_id: {job_id}")
    print(f"subgraph_ids: {subgraph_ids}")
