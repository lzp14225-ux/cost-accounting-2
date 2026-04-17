"""
线割工时计算脚本
负责人：李志鹏

计算流程：
1. 调用 wire_time_search 获取工时换算价格和 subgraphs 线割费用
2. 判断零件属于慢丝/中丝/快丝
3. 使用 对应线割费用 / wire_time.price 计算线割工时
4. 更新 subgraphs.wire_time
"""
from typing import List, Dict, Any, Tuple
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

MCP_TOOL_META = {
    "name": "calculate_wire_time",
    "description": "计算线割工时：按慢丝/中丝/快丝费用除以 wire_time 单价，回写 subgraphs.wire_time",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 wire_time"
            },
            "job_id": {
                "type": "string",
                "description": "任务ID (UUID)"
            },
            "subgraph_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "子图ID列表（可选）"
            }
        },
        "required": ["search_data"]
    },
    "handler": "calculate",
    "needs": ["wire_time"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    wire_time_data = search_data["wire_time"]

    if not job_id:
        job_id = wire_time_data.get("job_id")

    price_map = _build_wire_time_price_map(wire_time_data.get("wire_time_prices", []))
    parts = wire_time_data.get("parts", [])

    results = []
    updates = []
    for part in parts:
        result, update_data = _calculate_part_wire_time(part, price_map)
        results.append(result)
        updates.append(update_data)

    if updates:
        await _batch_update_subgraphs(job_id, updates)

    return {
        "job_id": job_id,
        "results": results
    }


def _normalize_wire_type(text: Any) -> str:
    value = str(text or "").strip().lower()
    if not value:
        return ""
    if "slow" in value or "慢丝" in value:
        return "slow"
    if "mid" in value or "middle" in value or "medium" in value or "中丝" in value:
        return "mid"
    if "fast" in value or "快丝" in value:
        return "fast"
    return value


def _build_wire_time_price_map(rules: List[Dict[str, Any]]) -> Dict[str, float]:
    price_map: Dict[str, float] = {}
    for rule in rules:
        wire_type = _normalize_wire_type(rule.get("sub_category"))
        if not wire_type:
            continue
        try:
            price_value = float(rule.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price_value > 0:
            price_map[wire_type] = price_value
    return price_map


def _detect_wire_type(part: Dict[str, Any]) -> Tuple[str, float]:
    slow_cost = float(part.get("slow_wire_cost") or 0)
    mid_cost = float(part.get("mid_wire_cost") or 0)
    fast_cost = float(part.get("fast_wire_cost") or 0)

    if slow_cost > 0:
        return "slow", slow_cost
    if mid_cost > 0:
        return "mid", mid_cost
    if fast_cost > 0:
        return "fast", fast_cost

    note_type = _normalize_wire_type(part.get("wire_process_note"))
    if note_type in {"slow", "mid", "fast"}:
        return note_type, 0.0

    code_type = _normalize_wire_type(part.get("wire_process"))
    if code_type in {"slow", "mid", "fast"}:
        return code_type, 0.0

    return "", 0.0


def _calculate_part_wire_time(part: Dict[str, Any], price_map: Dict[str, float]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    subgraph_id = part["subgraph_id"]
    part_name = part.get("part_name")
    wire_type, wire_cost = _detect_wire_type(part)
    unit_price = price_map.get(wire_type, 0.0)

    if not wire_type:
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "wire_type": None,
            "wire_cost": 0.0,
            "wire_time": 0.0,
            "note": "未识别到慢丝/中丝/快丝类型"
        }, {"subgraph_id": subgraph_id, "wire_time": 0.0}

    if unit_price <= 0:
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "wire_type": wire_type,
            "wire_cost": round(wire_cost, 2),
            "wire_time": 0.0,
            "note": f"未找到 {wire_type} 的 wire_time 单价"
        }, {"subgraph_id": subgraph_id, "wire_time": 0.0}

    wire_time = round(wire_cost / unit_price, 2) if wire_cost > 0 else 0.0
    return {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "wire_type": wire_type,
        "wire_cost": round(wire_cost, 2),
        "unit_price": unit_price,
        "wire_time": wire_time,
        "formula": f"{round(wire_cost, 2)} / {unit_price} = {wire_time}"
    }, {"subgraph_id": subgraph_id, "wire_time": wire_time}


async def _batch_update_subgraphs(job_id: str, updates: List[Dict[str, Any]]) -> None:
    sql = """
        UPDATE subgraphs
        SET wire_time = $3, updated_at = NOW()
        WHERE job_id = $1::uuid
          AND subgraph_id = $2
    """
    for item in updates:
        await db.execute(sql, job_id, item["subgraph_id"], item["wire_time"])


def calculate_sync(search_data: Dict[str, Any], job_id: str = None, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    return asyncio.run(calculate(search_data, job_id, subgraph_ids))
