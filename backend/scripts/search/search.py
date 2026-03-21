"""
Subgraphs 成本汇总检索脚本（阶段 5）
负责人：李志鹏

查询流程：
从 subgraphs 表读取各项成本总价
在 price_wire_total.py 和 price_water_mill_total.py 执行完成后调用

执行顺序：
阶段 1: 基础检索（并发）
阶段 2: 单价计算（并发）
阶段 3: 成本明细检索 (total_search)
阶段 4: 总价计算 (price_wire_total, price_water_mill_total)
阶段 5: 成本汇总检索 (本脚本) ← 从 subgraphs 表读取最终结果
"""
from typing import List, Dict, Any
import logging
import asyncio
import sys
import os

# 添加项目根目录到Python路径（用于直接运行脚本）
if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "search_subgraphs_cost_by_job_id",
    "description": "检索 subgraphs 表的成本汇总：获取各项总价（需在 price_wire_total 和 price_water_mill_total 执行后调用）。如果不传入subgraph_ids，则查询所有零件",
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
    "handler": "search_by_job_id",
    "depends_on": ["price_wire_total", "price_water_mill_total"]  # 声明依赖的计算脚本
}


async def search_by_job_id(job_id: str, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    """
    检索 subgraphs 表的成本汇总
    
    Args:
        job_id: 任务ID
        subgraph_ids: 子图ID列表（可选，如果为空则查询所有零件）
        
    Returns:
        Dict: {
            "data_type": "subgraphs_cost",
            "job_id": "...",
            "cost_summary": [
                {
                    "subgraph_id": "...",
                    "material_cost": 0.0,
                    "heat_treatment_cost": 0.0,
                    "large_grinding_cost": 0.0,
                    "small_grinding_cost": 0.0,
                    "slow_wire_cost": 0.0,
                    "slow_wire_side_cost": 0.0,
                    "mid_wire_cost": 0.0,
                    "fast_wire_cost": 0.0,
                    "edm_cost": 0.0,
                    "nc_z_fee": 0.0,
                    "nc_b_fee": 0.0,
                    "nc_c_fee": 0.0,
                    "nc_c_b_fee": 0.0,
                    "nc_z_view_fee": 0.0,
                    "nc_b_view_fee": 0.0
                },
                ...
            ]
        }
    """
    # 如果没有传入subgraph_ids或为空列表，则查询所有零件
    if not subgraph_ids:
        logger.info(f"Searching subgraphs cost summary for job_id: {job_id} (ALL parts)")
        # 查询该job_id下的所有零件
        sql = """
            SELECT 
                subgraph_id,
                material_cost,
                heat_treatment_cost,
                large_grinding_cost,
                small_grinding_cost,
                slow_wire_cost,
                slow_wire_side_cost,
                mid_wire_cost,
                fast_wire_cost,
                edm_cost,
                nc_z_fee,
                nc_b_fee,
                nc_c_fee,
                nc_c_b_fee,
                nc_z_view_fee,
                nc_b_view_fee
            FROM subgraphs
            WHERE job_id = $1::uuid
            ORDER BY subgraph_id
        """
        query_params = [job_id]
    else:
        logger.info(f"Searching subgraphs cost summary for job_id: {job_id}, subgraph_ids: {subgraph_ids}")
        # 查询指定的零件
        sql = """
            SELECT 
                subgraph_id,
                material_cost,
                heat_treatment_cost,
                large_grinding_cost,
                small_grinding_cost,
                slow_wire_cost,
                slow_wire_side_cost,
                mid_wire_cost,
                fast_wire_cost,
                edm_cost,
                nc_z_fee,
                nc_b_fee,
                nc_c_fee,
                nc_c_b_fee,
                nc_z_view_fee,
                nc_b_view_fee
            FROM subgraphs
            WHERE job_id = $1::uuid 
              AND subgraph_id = ANY($2::text[])
            ORDER BY subgraph_id
        """
        query_params = [job_id, subgraph_ids]
    
    try:
        rows = await db.fetch_all(sql, *query_params)
        
        # 转换为字典列表，处理 NULL 值
        cost_summary = []
        for row in rows:
            summary = {
                "subgraph_id": row["subgraph_id"],
                "material_cost": float(row["material_cost"]) if row["material_cost"] is not None else 0.0,
                "heat_treatment_cost": float(row["heat_treatment_cost"]) if row["heat_treatment_cost"] is not None else 0.0,
                "large_grinding_cost": float(row["large_grinding_cost"]) if row["large_grinding_cost"] is not None else 0.0,
                "small_grinding_cost": float(row["small_grinding_cost"]) if row["small_grinding_cost"] is not None else 0.0,
                "slow_wire_cost": float(row["slow_wire_cost"]) if row["slow_wire_cost"] is not None else 0.0,
                "slow_wire_side_cost": float(row["slow_wire_side_cost"]) if row["slow_wire_side_cost"] is not None else 0.0,
                "mid_wire_cost": float(row["mid_wire_cost"]) if row["mid_wire_cost"] is not None else 0.0,
                "fast_wire_cost": float(row["fast_wire_cost"]) if row["fast_wire_cost"] is not None else 0.0,
                "edm_cost": float(row["edm_cost"]) if row["edm_cost"] is not None else 0.0,
                "nc_z_fee": float(row["nc_z_fee"]) if row["nc_z_fee"] is not None else 0.0,
                "nc_b_fee": float(row["nc_b_fee"]) if row["nc_b_fee"] is not None else 0.0,
                "nc_c_fee": float(row["nc_c_fee"]) if row["nc_c_fee"] is not None else 0.0,
                "nc_c_b_fee": float(row["nc_c_b_fee"]) if row["nc_c_b_fee"] is not None else 0.0,
                "nc_z_view_fee": float(row["nc_z_view_fee"]) if row["nc_z_view_fee"] is not None else 0.0,
                "nc_b_view_fee": float(row["nc_b_view_fee"]) if row["nc_b_view_fee"] is not None else 0.0
            }
            cost_summary.append(summary)
        
        logger.info(f"Completed search, found {len(cost_summary)} cost summaries")
        
        return {
            "data_type": "subgraphs_cost",
            "job_id": job_id,
            "cost_summary": cost_summary
        }
    
    except Exception as e:
        logger.error(f"Failed to search subgraphs cost summary: {e}")
        raise


# 便捷同步调用接口
def search_by_job_id_sync(job_id: str, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    """同步版本的查询接口"""
    return asyncio.run(search_by_job_id(job_id, subgraph_ids))


# 测试入口
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 3:
        print("Usage: python search.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = search_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 查询结果 (job_id: {job_id}) ===")
    print(f"data_type: {results['data_type']}")
    print(f"找到 {len(results['cost_summary'])} 条成本汇总\n")
    
    for summary in results['cost_summary']:
        print(f"{'='*80}")
        print(f"subgraph_id: {summary['subgraph_id']}")
        print(f"{'='*80}")
        print(f"  material_cost: {summary['material_cost']} 元")
        print(f"  heat_treatment_cost: {summary['heat_treatment_cost']} 元")
        print(f"  large_grinding_cost: {summary['large_grinding_cost']} 元")
        print(f"  small_grinding_cost: {summary['small_grinding_cost']} 元")
        print(f"  slow_wire_cost: {summary['slow_wire_cost']} 元")
        print(f"  slow_wire_side_cost: {summary['slow_wire_side_cost']} 元")
        print(f"  mid_wire_cost: {summary['mid_wire_cost']} 元")
        print(f"  fast_wire_cost: {summary['fast_wire_cost']} 元")
        print(f"  edm_cost: {summary['edm_cost']} 元")
        print(f"  nc_z_fee: {summary['nc_z_fee']} 元")
        print(f"  nc_b_fee: {summary['nc_b_fee']} 元")
        print(f"  nc_c_fee: {summary['nc_c_fee']} 元")
        print(f"  nc_c_b_fee: {summary['nc_c_b_fee']} 元")
        print(f"  nc_z_view_fee: {summary['nc_z_view_fee']} 元")
        print(f"  nc_b_view_fee: {summary['nc_b_view_fee']} 元")
        print()
