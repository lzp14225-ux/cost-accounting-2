"""
基础零件信息检索脚本
负责人：李志鹏

查询流程：
Step 1: subgraphs表 -> 根据 job_id + subgraph_id 查询 part_name、part_code、wire_process_note、wire_process
Step 2: features表 -> 根据 job_id + subgraph_id 查询 length_mm、width_mm、thickness_mm、metadata、water_mill、quantity、boring_num、material、has_auto_material、has_material_preparation、needs_heat_treatment、nc_time_cost
Step 3: 合并零件基础信息和特征数据
"""
from typing import List, Dict, Any
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "search_base_itemcode_by_job_id",
    "description": "按job_id和subgraph_ids查询零件基础信息：从subgraphs获取part_name/part_code，从features获取尺寸和metadata",
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
                "description": "子图ID列表 (UUID数组)"
            }
        },
        "required": ["job_id", "subgraph_ids"]
    },
    "handler": "search_by_job_id"
}


async def search_by_job_id(job_id: str, subgraph_ids: List[str]) -> Dict[str, Any]:
    """
    按job_id和subgraph_ids查询零件基础信息
    
    Args:
        job_id: 任务ID (UUID字符串)
        subgraph_ids: 子图ID列表 (UUID字符串列表)
        
    Returns:
        Dict: {
            "parts": [
                {
                    "subgraph_id": "...",
                    "part_name": "...",
                    "part_code": "...",
                    "wire_process_note": "...",
                    "wire_process": "...",
                    "length_mm": ...,
                    "width_mm": ...,
                    "thickness_mm": ...,
                    "quantity": ...,
                    "boring_num": ...,
                    "material": "...",
                    "has_auto_material": true/false,
                    "has_material_preparation": "...",
                    "needs_heat_treatment": true/false,
                    "tooth_hole": {...},
                    "metadata": {...},
                    "water_mill": {...},
                    "nc_time_cost": {...}
                },
                ...
            ]
        }
    """
    logger.info(f"Searching base itemcode info for job_id: {job_id}, subgraph_ids: {subgraph_ids}")
    
    # 优化：使用 JOIN 一次查询获取所有数据
    parts = await _fetch_parts_with_join(job_id, subgraph_ids)
    
    logger.info(f"Completed search, matched {len(parts)} parts")
    
    return {
        "data_type": "base_itemcode",
        "job_id": job_id,
        "parts": parts
    }


async def _fetch_parts_with_join(job_id: str, subgraph_ids: List[str]) -> List[Dict]:
    """
    优化：使用 JOIN 一次查询获取 subgraphs 和 features 的所有数据
    
    Args:
        job_id: 任务ID
        subgraph_ids: 子图ID列表
    
    Returns:
        List[Dict]: 零件列表，包含所有字段
    """
    import json
    
    sql = """
        SELECT 
            s.subgraph_id,
            s.part_name,
            s.part_code,
            s.wire_process_note,
            s.wire_process,
            s.process_description,
            f.processing_instructions,
            f.length_mm,
            f.width_mm,
            f.thickness_mm,
            f.metadata,
            f.water_mill,
            f.quantity,
            f.boring_num,
            f.material,
            f.has_auto_material,
            f.has_material_preparation,
            f.needs_heat_treatment,
            f.heat_treatment,
            f.tooth_hole,
            f.nc_time_cost
        FROM subgraphs s
        LEFT JOIN features f 
            ON s.job_id = f.job_id AND s.subgraph_id = f.subgraph_id
        WHERE s.job_id = $1::uuid AND s.subgraph_id = ANY($2::text[])
    """
    try:
        rows = await db.fetch_all(sql, job_id, subgraph_ids)
        parts = []
        for row in rows:
            part = dict(row)
            
            # 确保 metadata 是字典类型
            if part.get("metadata") and isinstance(part["metadata"], str):
                try:
                    part["metadata"] = json.loads(part["metadata"])
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse metadata JSON for {part.get('subgraph_id')}: {e}")
                    part["metadata"] = None
            
            # 确保 water_mill 是字典类型
            if part.get("water_mill") and isinstance(part["water_mill"], str):
                try:
                    part["water_mill"] = json.loads(part["water_mill"])
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse water_mill JSON for {part.get('subgraph_id')}: {e}")
                    part["water_mill"] = None
            
            # 确保 tooth_hole 是字典类型
            if part.get("tooth_hole") and isinstance(part["tooth_hole"], str):
                try:
                    part["tooth_hole"] = json.loads(part["tooth_hole"])
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse tooth_hole JSON for {part.get('subgraph_id')}: {e}")
                    part["tooth_hole"] = None
            
            # 确保 nc_time_cost 是字典类型
            if part.get("nc_time_cost") and isinstance(part["nc_time_cost"], str):
                try:
                    part["nc_time_cost"] = json.loads(part["nc_time_cost"])
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse nc_time_cost JSON for {part.get('subgraph_id')}: {e}")
                    part["nc_time_cost"] = None
            
            parts.append(part)
        
        return parts
    except Exception as e:
        logger.error(f"Fetch parts with JOIN failed: {e}")
        raise


async def _fetch_subgraph_data(job_id: str, subgraph_ids: List[str]) -> List[Dict]:
    """
    Step 1: 查询 subgraphs 表
    条件: job_id + subgraph_id IN (...)
    获取: subgraph_id, part_name, part_code, wire_process_note, wire_process
    """
    sql = """
        SELECT subgraph_id, part_name, part_code, wire_process_note, wire_process
        FROM subgraphs
        WHERE job_id = $1::uuid AND subgraph_id = ANY($2::text[])
    """
    try:
        rows = await db.fetch_all(sql, job_id, subgraph_ids)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Fetch subgraph data failed: {e}")
        raise


async def _fetch_feature_data(job_id: str, subgraph_ids: List[str]) -> List[Dict]:
    """
    Step 2: 查询 features 表
    条件: job_id + subgraph_id IN (...)
    获取: subgraph_id, length_mm, width_mm, thickness_mm, metadata, water_mill, quantity, boring_num, material, has_auto_material, has_material_preparation, needs_heat_treatment, heat_treatment, nc_time_cost
    """
    sql = """
        SELECT subgraph_id, length_mm, width_mm, thickness_mm, metadata, water_mill, quantity, boring_num,
               material, has_auto_material, has_material_preparation, needs_heat_treatment, heat_treatment, tooth_hole, nc_time_cost
        FROM features
        WHERE job_id = $1::uuid AND subgraph_id = ANY($2::text[])
    """
    try:
        rows = await db.fetch_all(sql, job_id, subgraph_ids)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Fetch feature data failed: {e}")
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
        print("Usage: python base_itemcode_search.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = search_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 查询结果 (job_id: {job_id}) ===")
    print(f"data_type: {results['data_type']}")
    
    print("\n--- 零件列表 ---")
    for part in results["parts"]:
        print(f"  subgraph_id: {part['subgraph_id']}")
        print(f"    part_name: {part['part_name']}, part_code: {part['part_code']}")
        print(f"    wire_process_note: {part['wire_process_note']}, wire_process: {part['wire_process']}")
        print(f"    尺寸: {part['length_mm']}x{part['width_mm']}x{part['thickness_mm']} mm")
        print(f"    数量: {part['quantity']}")
        print(f"    boring_num: {part['boring_num']}")
        print(f"    material: {part['material']}")
        print(f"    has_auto_material: {part['has_auto_material']}")
        print(f"    has_material_preparation: {part['has_material_preparation']}")
        print(f"    needs_heat_treatment: {part['needs_heat_treatment']}")
        print(f"    tooth_hole: {part['tooth_hole']}")
        print(f"    metadata: {part['metadata']}")
        print(f"    water_mill: {part['water_mill']}")
        print(f"    nc_time_cost: {part['nc_time_cost']}")
        print(f"    process_description: {part['process_description']}")
        print(f"    processing_instructions: {part['processing_instructions']}")
