"""
成本明细检索脚本
负责人：李志鹏

查询流程：
从 processing_cost_calculation_details 表读取各项成本单价
在所有计算脚本执行完成后调用
"""
from typing import List, Dict, Any
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "search_total_by_job_id",
    "description": "检索成本明细：从 processing_cost_calculation_details 表获取各项单价",
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
                "description": "子图ID列表"
            }
        },
        "required": ["job_id", "subgraph_ids"]
    },
    "handler": "search_by_job_id"
}


async def search_by_job_id(job_id: str, subgraph_ids: List[str]) -> Dict[str, Any]:
    """
    检索成本明细
    
    Args:
        job_id: 任务ID
        subgraph_ids: 子图ID列表
        
    Returns:
        Dict: {
            "data_type": "total",
            "job_id": "...",
            "cost_details": [
                {
                    "subgraph_id": "...",
                    "weight": 5.664,
                    "basic_processing_cost": 0.0,
                    "special_base_cost": 0.0,
                    "standard_base_cost": 0.0,
                    "material_additional_cost": 0.0,
                    "material_cost": 66.83,
                    "heat_treatment_cost": 21.52,
                    "thread_ends_cost": 0.0,
                    "hanging_table_cost": 0.0,
                    "chamfer_cost": 0.0,
                    "bevel_cost": 0.0,
                    "oil_tank_cost": 0.0,
                    "high_cost": 0.0,
                    "grinding_cost": 0.0,
                    "plate_cost": 0.0,
                    "long_strip_cost": 0.0,
                    "component_cost": 0.0,
                    "tooth_hole_cost": 0.0,
                    "tooth_hole_time_cost": 0.0,
                    "nc_base_cost": 0.0,
                    "nc_z_cost": 0.0,
                    "nc_b_cost": 0.0,
                    "nc_c_cost": 0.0,
                    "nc_c_b_cost": 0.0,
                    "nc_z_view_cost": 0.0,
                    "nc_b_view_cost": 0.0,
                    "calculation_steps": [...]
                },
                ...
            ]
        }
    """
    logger.info(f"Searching cost details for job_id: {job_id}, subgraph_ids: {subgraph_ids}")
    
    # 查询 processing_cost_calculation_details 表
    sql = """
        SELECT 
            subgraph_id,
            weight,
            basic_processing_cost,
            special_base_cost,
            standard_base_cost,
            material_additional_cost,
            material_cost,
            heat_treatment_cost,
            thread_ends_cost,
            hanging_table_cost,
            chamfer_cost,
            bevel_cost,
            oil_tank_cost,
            high_cost,
            grinding_cost,
            plate_cost,
            long_strip_cost,
            component_cost,
            tooth_hole_cost,
            tooth_hole_time_cost,
            nc_base_cost,
            nc_z_cost,
            nc_b_cost,
            nc_c_cost,
            nc_c_b_cost,
            nc_z_view_cost,
            nc_b_view_cost,
            calculation_steps
        FROM processing_cost_calculation_details
        WHERE job_id = $1::uuid 
          AND subgraph_id = ANY($2::text[])
    """
    
    try:
        rows = await db.fetch_all(sql, job_id, subgraph_ids)
        
        # 转换为字典列表，处理 NULL 值
        cost_details = []
        for row in rows:
            # 处理 calculation_steps：如果是字符串，尝试解析为 JSON
            calc_steps = row["calculation_steps"]
            if calc_steps is not None:
                if isinstance(calc_steps, str):
                    # 如果是字符串，尝试解析为 JSON
                    import json
                    try:
                        calc_steps = json.loads(calc_steps)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse calculation_steps as JSON for {row['subgraph_id']}")
                        calc_steps = []
            else:
                calc_steps = []
            
            detail = {
                "subgraph_id": row["subgraph_id"],
                "weight": float(row["weight"]) if row["weight"] is not None else 0.0,
                "basic_processing_cost": float(row["basic_processing_cost"]) if row["basic_processing_cost"] is not None else 0.0,
                "special_base_cost": float(row["special_base_cost"]) if row["special_base_cost"] is not None else 0.0,
                "standard_base_cost": float(row["standard_base_cost"]) if row["standard_base_cost"] is not None else 0.0,
                "material_additional_cost": float(row["material_additional_cost"]) if row["material_additional_cost"] is not None else 0.0,
                "material_cost": float(row["material_cost"]) if row["material_cost"] is not None else 0.0,
                "heat_treatment_cost": float(row["heat_treatment_cost"]) if row["heat_treatment_cost"] is not None else 0.0,
                "thread_ends_cost": float(row["thread_ends_cost"]) if row["thread_ends_cost"] is not None else 0.0,
                "hanging_table_cost": float(row["hanging_table_cost"]) if row["hanging_table_cost"] is not None else 0.0,
                "chamfer_cost": float(row["chamfer_cost"]) if row["chamfer_cost"] is not None else 0.0,
                "bevel_cost": float(row["bevel_cost"]) if row["bevel_cost"] is not None else 0.0,
                "oil_tank_cost": float(row["oil_tank_cost"]) if row["oil_tank_cost"] is not None else 0.0,
                "high_cost": float(row["high_cost"]) if row["high_cost"] is not None else 0.0,
                "grinding_cost": float(row["grinding_cost"]) if row["grinding_cost"] is not None else 0.0,
                "plate_cost": float(row["plate_cost"]) if row["plate_cost"] is not None else 0.0,
                "long_strip_cost": float(row["long_strip_cost"]) if row["long_strip_cost"] is not None else 0.0,
                "component_cost": float(row["component_cost"]) if row["component_cost"] is not None else 0.0,
                "tooth_hole_cost": float(row["tooth_hole_cost"]) if row["tooth_hole_cost"] is not None else 0.0,
                "tooth_hole_time_cost": float(row["tooth_hole_time_cost"]) if row["tooth_hole_time_cost"] is not None else 0.0,
                "nc_base_cost": float(row["nc_base_cost"]) if row["nc_base_cost"] is not None else 0.0,
                "nc_z_cost": float(row["nc_z_cost"]) if row["nc_z_cost"] is not None else 0.0,
                "nc_b_cost": float(row["nc_b_cost"]) if row["nc_b_cost"] is not None else 0.0,
                "nc_c_cost": float(row["nc_c_cost"]) if row["nc_c_cost"] is not None else 0.0,
                "nc_c_b_cost": float(row["nc_c_b_cost"]) if row["nc_c_b_cost"] is not None else 0.0,
                "nc_z_view_cost": float(row["nc_z_view_cost"]) if row["nc_z_view_cost"] is not None else 0.0,
                "nc_b_view_cost": float(row["nc_b_view_cost"]) if row["nc_b_view_cost"] is not None else 0.0,
                "calculation_steps": calc_steps
            }
            cost_details.append(detail)
        
        logger.info(f"Completed search, found {len(cost_details)} cost details")
        
        return {
            "data_type": "total",
            "job_id": job_id,
            "cost_details": cost_details
        }
    
    except Exception as e:
        logger.error(f"Failed to search cost details: {e}")
        raise


# 便捷同步调用接口
def search_by_job_id_sync(job_id: str, subgraph_ids: List[str]) -> Dict[str, Any]:
    """同步版本的查询接口"""
    return asyncio.run(search_by_job_id(job_id, subgraph_ids))


# 测试入口
if __name__ == "__main__":
    import sys
    import os
    
    # 添加项目根目录到Python路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 3:
        print("Usage: python total_search.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = search_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 查询结果 (job_id: {job_id}) ===")
    print(f"data_type: {results['data_type']}")
    print(f"找到 {len(results['cost_details'])} 条成本明细\n")
    
    for detail in results['cost_details']:
        print(f"{'='*80}")
        print(f"subgraph_id: {detail['subgraph_id']}")
        print(f"{'='*80}")
        print(f"  weight: {detail['weight']} kg")
        print(f"  material_cost: {detail['material_cost']} 元")
        print(f"  heat_treatment_cost: {detail['heat_treatment_cost']} 元")
        print(f"  basic_processing_cost: {detail['basic_processing_cost']} 元")
        print(f"  special_base_cost: {detail['special_base_cost']} 元")
        print(f"  standard_base_cost: {detail['standard_base_cost']} 元")
        print(f"  material_additional_cost: {detail['material_additional_cost']} 元")
        print(f"  thread_ends_cost: {detail['thread_ends_cost']} 元")
        print(f"  hanging_table_cost: {detail['hanging_table_cost']} 元")
        print(f"  chamfer_cost: {detail['chamfer_cost']} 元")
        print(f"  bevel_cost: {detail['bevel_cost']} 元")
        print(f"  oil_tank_cost: {detail['oil_tank_cost']} 元")
        print(f"  high_cost: {detail['high_cost']} 元")
        print(f"  grinding_cost: {detail['grinding_cost']} 元")
        print(f"  plate_cost: {detail['plate_cost']} 元")
        print(f"  long_strip_cost: {detail['long_strip_cost']} 小时")
        print(f"  component_cost: {detail['component_cost']} 小时")
        print(f"  tooth_hole_cost: {detail['tooth_hole_cost']} 元")
        print(f"  tooth_hole_time_cost: {detail['tooth_hole_time_cost']} 元")
        print(f"  nc_base_cost: {detail['nc_base_cost']} 小时")
        print(f"  nc_z_cost: {detail['nc_z_cost']} 小时")
        print(f"  nc_b_cost: {detail['nc_b_cost']} 小时")
        print(f"  nc_c_cost: {detail['nc_c_cost']} 小时")
        print(f"  nc_c_b_cost: {detail['nc_c_b_cost']} 小时")
        print(f"  nc_z_view_cost: {detail['nc_z_view_cost']} 小时")
        print(f"  nc_b_view_cost: {detail['nc_b_view_cost']} 小时")
        
        # 显示 calculation_steps 的详细信息
        print(f"\n  calculation_steps:")
        steps = detail['calculation_steps']
        if isinstance(steps, list):
            print(f"    共 {len(steps)} 个类别\n")
            for i, step_category in enumerate(steps, 1):
                if isinstance(step_category, dict):
                    category = step_category.get('category', 'unknown')
                    steps_list = step_category.get('steps', [])
                    print(f"    [{i}] 类别: {category}")
                    print(f"        步骤数: {len(steps_list)}")
                    
                    # 显示每个步骤的详细信息
                    for j, step in enumerate(steps_list, 1):
                        if isinstance(step, dict):
                            step_name = step.get('step', 'unknown')
                            print(f"        步骤 {j}: {step_name}")
                            # 显示步骤的关键信息（排除 step 字段本身）
                            for key, value in step.items():
                                if key != 'step':
                                    # 格式化输出，避免过长
                                    if isinstance(value, (int, float, str, bool)):
                                        print(f"          - {key}: {value}")
                                    elif isinstance(value, dict):
                                        print(f"          - {key}: {{...}} (字典)")
                                    elif isinstance(value, list):
                                        print(f"          - {key}: [...] (列表，{len(value)} 项)")
                                    else:
                                        print(f"          - {key}: {type(value).__name__}")
                    print()
        else:
            print(f"    类型: {type(steps).__name__} (非列表类型)")
        print()
