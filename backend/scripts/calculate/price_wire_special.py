"""
线割特殊价格计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（length_mm, width_mm, thickness_mm, metadata, quantity）
2. 调用 wire_special_search 获取特殊价格信息（sub_category、price、min_num、note 等）
3. 检查 metadata 是否为空，为空则跳过计算返回0
4. 根据 template_component 配置判断是否为模板：任意尺寸 > 阈值
5. 计算 special1：按线割类型、模板/零件类型、最长边匹配 min_num 区间后取动态价格
6. 计算 special2：如果有侧割（front_view 或 side_view 的 total_length 不为0），按线割类型和最长边匹配动态价格
7. 计算公式：special_base_cost = special1 + special2
8. 更新 processing_cost_calculation_details 表的 special_base_cost 字段和步骤字段
"""
from typing import List, Dict, Any
import logging
import asyncio
import json
import re

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_wire_special_price",
    "description": "计算线割特殊价格：根据线割类型、模板/零件类型、最长边区间和侧割情况计算特殊加工费用",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 wire_special"
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
    "needs": ["base_itemcode", "wire_special"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算线割特殊价格
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 wire_special
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    special_data = search_data["wire_special"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating wire special price for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 3: 构建价格映射，保留 min_num 区间和 note 用于动态匹配与明细记录
    price_map = _build_price_map(special_data.get("special_prices", []))
    
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
                "value": d["special_base_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "wire_special", "special_base_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(special_prices: List[Dict]) -> Dict[str, Any]:
    """
    构建特殊价格映射。
    同一个 sub_category 可以有多条价格规则，通过 min_num 区间动态匹配最长边。
    
    Returns:
        {
            "template_threshold": 400,
            "slow_template": [{"price": 80, "min_num": None, ...}],
            "medium_template": [{"price": 60, "min_num": "[400,800)", ...}, ...],
            ...
        }
    """
    price_map = {
        "template_threshold": 400
    }
    
    for price in special_prices:
        sub_category = price.get("sub_category")
        price_value = price.get("price")
        min_num = price.get("min_num")
        note = price.get("note")
        
        try:
            if sub_category == "template_component":
                price_map["template_threshold"] = float(price_value)
            else:
                rule = {
                    "price": float(price_value),
                    "min_num": min_num,
                    "note": note
                }
                interval = _parse_interval(min_num)
                has_min_num = min_num is not None and str(min_num).strip().lower() not in ("", "none", "null")
                if has_min_num and not interval:
                    logger.warning(f"Skipping wire special rule with invalid min_num: {sub_category}, min_num={min_num}")
                    continue
                if interval:
                    rule.update(interval)
                
                price_map.setdefault(sub_category, []).append(rule)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse price for {sub_category}: {price_value}, error: {e}")
    
    return price_map


def _parse_interval(min_num: Any) -> Dict[str, Any] | None:
    """
    解析 min_num 区间，格式如: [400,800)、[800,99999)
    支持左右开闭区间。
    """
    if min_num is None:
        return None

    min_num_str = str(min_num).strip()
    if not min_num_str:
        return None

    match = re.match(r'([\[\(])\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?|[+∞∞]+)\s*([\]\)])', min_num_str)
    if not match:
        logger.warning(f"Invalid wire special min_num format: {min_num}")
        return None

    min_bracket = match.group(1)
    min_val = float(match.group(2))
    max_str = match.group(3)
    max_bracket = match.group(4)
    max_val = float("inf") if "+" in max_str or "∞" in max_str else float(max_str)

    return {
        "min": min_val,
        "max": max_val,
        "min_inclusive": min_bracket == "[",
        "max_inclusive": max_bracket == "]"
    }


def _matches_interval(value: float, rule: Dict[str, Any]) -> bool:
    """判断最长边是否命中规则区间。"""
    if "min" not in rule or "max" not in rule:
        return True

    min_ok = value >= rule["min"] if rule["min_inclusive"] else value > rule["min"]
    max_ok = value <= rule["max"] if rule["max_inclusive"] else value < rule["max"]
    return min_ok and max_ok


def _get_price_by_dimension(price_map: Dict[str, Any], fee_key: str, max_dimension: float) -> tuple[float, Dict[str, Any] | None]:
    """
    按 fee_key 和最长边匹配价格。
    如果规则带 min_num，则按区间匹配；没有 min_num 的规则作为固定价兼容。
    """
    rules = price_map.get(fee_key, [])
    if isinstance(rules, (int, float)):
        return float(rules), None

    fallback_rule = None
    for rule in rules:
        if "min" not in rule or "max" not in rule:
            fallback_rule = rule
            continue
        if _matches_interval(max_dimension, rule):
            return rule["price"], rule

    if fallback_rule:
        return fallback_rule["price"], fallback_rule

    logger.warning(f"No wire special price matched for {fee_key}, max_dimension={max_dimension}")
    return 0, None


def _get_wire_type(wire_process_note: str) -> str:
    """
    根据 wire_process_note 判断线割类型
    
    Returns:
        "slow" | "medium" | "fast"
    """
    if not wire_process_note:
        return "fast"  # 默认快丝
    
    wire_process_note = str(wire_process_note)
    
    if "慢丝" in wire_process_note:
        return "slow"
    elif "中丝" in wire_process_note:
        return "medium"
    elif "快丝" in wire_process_note:
        return "fast"
    else:
        return "fast"  # 默认快丝


def _is_template(length_mm: float, width_mm: float, thickness_mm: float, threshold: float) -> tuple[bool, bool]:
    """
    判断是否为模板。
    任意一个尺寸 > threshold 则为模板，threshold 来自 template_component 配置。
    
    Returns:
        tuple: (is_template, is_valid)
            - is_template: 是否为模板
            - is_valid: 尺寸数据是否有效（必须大于0）
    """
    dimensions = [length_mm, width_mm, thickness_mm]
    max_dimension = max(d for d in dimensions if d is not None)
    
    # 尺寸必须大于0才有效
    is_valid = max_dimension > 0
    is_template = max_dimension > threshold
    
    return is_template, is_valid


def _has_side_cut(metadata: Dict) -> bool:
    """
    判断是否有侧割
    检查 metadata 中 view 为 front_view 或 side_view 的 total_length 是否不为0
    """
    if not metadata or "wire_cut_details" not in metadata:
        return False
    
    wire_cut_details = metadata["wire_cut_details"]
    
    for detail in wire_cut_details:
        view = detail.get("view")
        total_length = detail.get("total_length", 0)
        
        if view in ["front_view", "side_view"] and total_length != 0:
            return True
    
    return False


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的线割特殊价格
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    wire_process_note = part.get("wire_process_note")  # 例如: 慢丝割一修一
    length_mm = part.get("length_mm") or 0
    width_mm = part.get("width_mm") or 0
    thickness_mm = part.get("thickness_mm") or 0
    metadata = part.get("metadata")
    
    logger.info(f"Calculating special price for part: {part_name} ({subgraph_id}), wire_process_note: {wire_process_note}")
    
    # 检查 metadata
    if not metadata:
        logger.info(f"No metadata for {part_name}, skipping wire_special calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "special_base_cost": 0,
            "note": "metadata为空，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "special_base_cost": 0,
            "calculation_steps": [{
                "step": "检查metadata",
                "note": "metadata为空，跳过线割特殊价格计算"
            }]
        }
    
    # 如果 metadata 是字符串，解析为 JSON
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception as e:
            logger.info(f"Failed to parse metadata JSON for {part_name}: {e}, skipping calculation")
            return {
                "subgraph_id": subgraph_id,
                "part_name": part_name,
                "special_base_cost": 0,
                "note": f"metadata JSON解析失败，跳过计算"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "special_base_cost": 0,
                "calculation_steps": [{
                    "step": "解析metadata",
                    "note": f"JSON解析失败: {e}，跳过线割特殊价格计算"
                }]
            }
    
    # 确保 metadata 是字典类型
    if not isinstance(metadata, dict):
        logger.info(f"metadata is not a dict for {part_name}, skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "special_base_cost": 0,
            "note": "metadata类型错误，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "special_base_cost": 0,
            "calculation_steps": [{
                "step": "检查metadata类型",
                "note": "metadata不是字典类型，跳过线割特殊价格计算"
            }]
        }
    
    # 获取价格配置
    template_threshold = price_map.get("template_threshold", 400)
    
    # 判断线割类型
    wire_type = _get_wire_type(wire_process_note)
    
    # 计算步骤
    calculation_steps = []
    
    # Step 1: 判断线割类型
    calculation_steps.append({
        "step": "判断线割类型",
        "wire_process_note": wire_process_note,
        "wire_type": wire_type
    })
    
    # Step 2: 判断是否为模板
    is_template, is_valid = _is_template(length_mm, width_mm, thickness_mm, template_threshold)
    max_dimension = max(length_mm, width_mm, thickness_mm)
    
    # 如果尺寸无效（≤0），跳过计算
    if not is_valid:
        logger.info(f"Invalid dimensions for {part_name} (max={max_dimension}mm), skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "special_base_cost": 0,
            "note": f"尺寸数据无效（最大尺寸={max_dimension}mm），跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "special_base_cost": 0,
            "calculation_steps": [{
                "step": "验证尺寸数据",
                "dimensions": {
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "thickness_mm": thickness_mm,
                    "max_dimension": max_dimension
                },
                "status": "failed",
                "reason": f"最大尺寸{max_dimension}mm ≤ 0，数据无效",
                "note": "尺寸必须大于0才能计算"
            }]
        }
    
    calculation_steps.append({
        "step": "判断零件类型",
        "dimensions": {
            "length_mm": length_mm,
            "width_mm": width_mm,
            "thickness_mm": thickness_mm,
            "max_dimension": max_dimension
        },
        "threshold": template_threshold,
        "is_template": is_template,
        "reason": f"最大尺寸{max_dimension}mm {'>' if is_template else '<='} {template_threshold}mm"
    })
    
    # Step 3: 计算 special1（模板费或零件费），按最长边匹配 min_num 区间
    if is_template:
        fee_key = f"{wire_type}_template"
    else:
        fee_key = f"{wire_type}_component"
    special1, special1_rule = _get_price_by_dimension(price_map, fee_key, max_dimension)
    
    calculation_steps.append({
        "step": "计算基础费用(special1)",
        "fee_type": fee_key,
        "max_dimension": max_dimension,
        "matched_min_num": special1_rule.get("min_num") if special1_rule else None,
        "matched_note": special1_rule.get("note") if special1_rule else None,
        "amount": special1
    })
    
    # Step 4: 判断是否有侧割
    has_side_cut = _has_side_cut(metadata)
    
    side_cut_details = []
    if metadata and "wire_cut_details" in metadata:
        for detail in metadata["wire_cut_details"]:
            view = detail.get("view")
            total_length = detail.get("total_length", 0)
            if view in ["front_view", "side_view"]:
                side_cut_details.append({
                    "view": view,
                    "total_length": total_length
                })
    
    calculation_steps.append({
        "step": "判断是否有侧割",
        "side_cut_details": side_cut_details,
        "has_side_cut": has_side_cut
    })
    
    # Step 5: 计算 special2（侧割费），有侧割时按最长边匹配 min_num 区间
    side_cut_key = f"{wire_type}_side"
    special2_rule = None
    if has_side_cut:
        special2, special2_rule = _get_price_by_dimension(price_map, side_cut_key, max_dimension)
    else:
        special2 = 0
    
    calculation_steps.append({
        "step": "计算侧割费用(special2)",
        "fee_type": side_cut_key if has_side_cut else "无侧割",
        "has_side_cut": has_side_cut,
        "max_dimension": max_dimension if has_side_cut else None,
        "matched_min_num": special2_rule.get("min_num") if special2_rule else None,
        "matched_note": special2_rule.get("note") if special2_rule else None,
        "amount": special2
    })
    
    # Step 6: 计算总特殊费用
    special_base_cost = special1 + special2
    
    calculation_steps.append({
        "step": "计算总特殊费用",
        "formula": f"{special1} + {special2}",
        "special_base_cost": round(special_base_cost, 2)
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "wire_type": wire_type,
        "is_template": is_template,
        "has_side_cut": has_side_cut,
        "special_base_cost": round(special_base_cost, 2)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "special_base_cost": special_base_cost,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _update_calculation_details(
    job_id: str,
    subgraph_id: str,
    special_base_cost: float,
    new_steps: List[Dict]
):
    """
    更新 processing_cost_calculation_details 表（保留用于向后兼容）
    """
    await batch_upsert_with_steps(
        [{
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "value": special_base_cost,
            "steps": new_steps
        }],
        "wire_special",
        "special_base_cost"
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
        print("Usage: python price_wire_special.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = calculate_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 计算结果 (job_id: {job_id}) ===")
    for result in results["results"]:
        print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
        print(f"  线割类型: {result['wire_type']}")
        print(f"  是否为模板: {result['is_template']}")
        print(f"  是否有侧割: {result['has_side_cut']}")
        print(f"  特殊加工费: {result['special_base_cost']} 元")
