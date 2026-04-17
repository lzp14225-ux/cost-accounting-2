"""
线割工时检索脚本
负责人：李志鹏

查询流程：
Step 1: job_price_snapshots表 -> 查询 category 为 wire_time 的 sub_category、price、unit、note
Step 2: subgraphs表 -> 根据 job_id + subgraph_id 查询 slow_wire_cost、mid_wire_cost、fast_wire_cost
"""
from typing import List, Dict, Any
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

MCP_TOOL_META = {
    "name": "search_wire_time_by_job_id",
    "description": "按job_id查询线割工时换算规则，并按subgraph_ids查询零件的线割费用字段",
    "inputSchema": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "任务ID (UUID)"
            },
            "subgraph_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "子图ID列表（可选，如果为空则查询所有零件）"
            }
        },
        "required": ["job_id"]
    },
    "handler": "search_by_job_id"
}


async def search_by_job_id(job_id: str, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    logger.info(f"Searching wire_time data for job_id: {job_id}, subgraph_ids={subgraph_ids}")

    wire_time_prices = await _fetch_wire_time_prices(job_id)
    parts = await _fetch_subgraph_wire_costs(job_id, subgraph_ids)

    logger.info(
        f"Completed wire_time search: rules={len(wire_time_prices)}, parts={len(parts)}"
    )

    return {
        "data_type": "wire_time",
        "job_id": job_id,
        "wire_time_prices": wire_time_prices,
        "parts": parts
    }


async def _fetch_wire_time_prices(job_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT DISTINCT sub_category, price, unit, note
        FROM job_price_snapshots
        WHERE job_id = $1::uuid AND category = 'wire_time'
        ORDER BY sub_category
    """
    rows = await db.fetch_all(sql, job_id)
    return [dict(row) for row in rows]


async def _fetch_subgraph_wire_costs(job_id: str, subgraph_ids: List[str] = None) -> List[Dict[str, Any]]:
    if subgraph_ids:
        sql = """
            SELECT
                subgraph_id,
                part_name,
                part_code,
                wire_process,
                wire_process_note,
                slow_wire_cost,
                mid_wire_cost,
                fast_wire_cost,
                wire_time
            FROM subgraphs
            WHERE job_id = $1::uuid
              AND subgraph_id = ANY($2::text[])
            ORDER BY part_code, subgraph_id
        """
        params = [job_id, subgraph_ids]
    else:
        sql = """
            SELECT
                subgraph_id,
                part_name,
                part_code,
                wire_process,
                wire_process_note,
                slow_wire_cost,
                mid_wire_cost,
                fast_wire_cost,
                wire_time
            FROM subgraphs
            WHERE job_id = $1::uuid
            ORDER BY part_code, subgraph_id
        """
        params = [job_id]

    rows = await db.fetch_all(sql, *params)
    parts = []
    for row in rows:
        parts.append({
            "subgraph_id": row["subgraph_id"],
            "part_name": row["part_name"],
            "part_code": row["part_code"],
            "wire_process": row["wire_process"],
            "wire_process_note": row["wire_process_note"],
            "slow_wire_cost": float(row["slow_wire_cost"]) if row["slow_wire_cost"] is not None else 0.0,
            "mid_wire_cost": float(row["mid_wire_cost"]) if row["mid_wire_cost"] is not None else 0.0,
            "fast_wire_cost": float(row["fast_wire_cost"]) if row["fast_wire_cost"] is not None else 0.0,
            "wire_time": float(row["wire_time"]) if row["wire_time"] is not None else None,
        })
    return parts


def search_by_job_id_sync(job_id: str, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    return asyncio.run(search_by_job_id(job_id, subgraph_ids))
