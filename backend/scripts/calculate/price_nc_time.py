"""
NC时间费用计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（nc_time_cost）
2. 调用 nc_search 获取NC工时价格信息（nc_base 和 work_hour）
3. 检查 nc_time_cost 是否为空，为空则跳过计算返回0
4. 按 face_code 分组计算：
   - 遍历每个 face_code 下的 details
   - 分类统计：精铣（精铣、半精、全精）、开粗（开粗）、钻床（其他所有code）
   - 将该 face_code 下的所有 value 相加得到总值
5. 更新 processing_cost_calculation_details 表的对应字段：
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

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

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

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_nc_time_cost",
    "description": "计算NC时间费用：按face_code分组计算各面的NC时间总值",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 nc"
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
    "needs": ["base_itemcode", "nc"]
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
        # 保留汇总步骤（没有 face_code 字段）
        elif "汇总" in step_name or "检查" in step_name or "解析" in step_name:
            filtered_steps.append(step)
    
    return filtered_steps


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算NC时间费用
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 nc
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    nc_data = search_data["nc"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating NC time cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 1: 计算每个零件的NC时间费用
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_nc_time_cost(job_id, part)
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
    
    logger.info(f"Completed NC time cost calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _calculate_part_nc_time_cost(
    job_id: str,
    part: Dict
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的NC时间费用
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    nc_time_cost_data = part.get("nc_time_cost")
    
    logger.info(f"Calculating NC time cost for part: {part_name} ({subgraph_id})")
    
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
                "note": "nc_time_cost数据为空，跳过NC时间费用计算"
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
                    "note": f"JSON解析失败: {e}，跳过NC时间费用计算"
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
                "note": "nc_details为空，跳过NC时间费用计算"
            }]
        }
    
    calculation_steps = []
    face_costs = {}  # 存储每个 face_code 的总值
    
    # 按 face_code 分组计算
    for nc_detail in nc_details:
        face_code = nc_detail.get("face_code", "")
        details = nc_detail.get("details", [])
        
        if not face_code or not details:
            continue
        
        # 分类统计：精铣、开粗、钻床
        jing_xi_total = 0  # 精铣
        kai_cu_total = 0   # 开粗
        drill_total = 0    # 钻床
        
        detail_breakdown = []
        
        for detail in details:
            code = detail.get("code", "")
            value = detail.get("value", 0)
            
            try:
                value_float = float(value)
            except (ValueError, TypeError):
                logger.warning(f"Invalid value for code {code}: {value}, skipping")
                continue
            
            # 分类逻辑
            if code in ["精铣", "半精", "全精"]:
                jing_xi_total += value_float
                category = "精铣"
            elif code == "开粗":
                kai_cu_total += value_float
                category = "开粗"
            else:
                drill_total += value_float
                category = "钻床"
            
            detail_breakdown.append({
                "code": code,
                "value": value_float,
                "category": category
            })
        
        # 计算该 face_code 的总值（分钟转小时）
        face_total_minutes = jing_xi_total + kai_cu_total + drill_total
        face_total_hours = round(face_total_minutes / 60.0, 2)  # 转换为小时，保留2位小数
        face_costs[face_code] = face_total_hours
        
        # 添加计算步骤
        if face_total_minutes > 0:
            calculation_steps.append({
                "step": f"计算 {face_code} 面",
                "face_code": face_code,
                "details": detail_breakdown,
                "summary": {
                    "精铣": round(jing_xi_total, 2),
                    "开粗": round(kai_cu_total, 2),
                    "钻床": round(drill_total, 2)
                },
                "total_minutes": round(face_total_minutes, 2),
                "formula": f"({round(jing_xi_total, 2)} + {round(kai_cu_total, 2)} + {round(drill_total, 2)}) / 60 = {face_total_hours}",
                "total_hours": face_total_hours,
                "note": "已将分钟转换为小时"
            })
        else:
            calculation_steps.append({
                "step": f"计算 {face_code} 面",
                "face_code": face_code,
                "note": "该面总值为0"
            })
    
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
        "face_costs": {k: round(v, 2) for k, v in face_costs.items()}
    }
    
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
