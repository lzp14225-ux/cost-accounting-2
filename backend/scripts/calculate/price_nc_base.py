"""
NC基本时间计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（length_mm, width_mm, thickness_mm, nc_time_cost）
2. 调用 nc_search 获取NC基本时间配置（nc_base: 模板1小时/零件0.5小时）
3. 调用 wire_base_search 获取模板零件判断标准（template_component: 默认400mm）
4. 检查 nc_time_cost 是否为空，为空则跳过计算返回0
5. 根据尺寸判断是模板还是零件：
   - 任意尺寸 > 400mm：模板（nc_base = 1小时）
   - 所有尺寸 <= 400mm：零件（nc_base = 0.5小时）
6. 更新 processing_cost_calculation_details 表的 nc_base_cost 字段（存储时间，单位：小时）
"""
from typing import List, Dict, Any, Tuple
import logging
import asyncio

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_nc_base_cost",
    "description": "计算NC基本时间：根据零件尺寸判断是模板还是零件，然后返回对应的基本时间",
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


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算NC基本时间
    
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
    
    logger.info(f"Calculating NC base time for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 1: 构建NC基本时间配置
    nc_base_config = _build_nc_base_config(nc_data.get("nc_prices", []))
    
    if not nc_base_config:
        logger.warning("No nc_base configuration found in nc_data")
        return {
            "job_id": job_id,
            "results": [],
            "message": "未找到NC基本时间配置"
        }
    
    # Step 2: 获取模板零件判断标准
    template_threshold = _get_template_threshold(wire_base_data.get("rule_prices", []))
    
    logger.info(f"Template threshold: {template_threshold} mm")
    
    # Step 3: 计算每个零件的NC基本时间
    results = []
    db_updates = []
    
    for part in base_data["parts"]:
        result, db_data = await _calculate_part_nc_base_time(
            job_id, part, nc_base_config, template_threshold
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # Step 4: 批量写入数据库
    if db_updates:
        updates = [
            {
                "job_id": d["job_id"],
                "subgraph_id": d["subgraph_id"],
                "value": d["nc_base_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates, "nc_base", "nc_base_cost")
    
    logger.info(f"Completed NC base time calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_nc_base_config(nc_prices: List[Dict]) -> Dict[str, Any]:
    """
    构建NC基本时间配置
    
    Returns:
        {
            "nc_base_hours": {
                "template": 1.0,    # 模板的nc_base时间
                "component": 0.5    # 零件的nc_base时间
            }
        }
    """
    nc_base_hours = {}
    
    for item in nc_prices:
        sub_category = item.get("sub_category")
        min_num = str(item.get("min_num") or "").strip()
        
        if sub_category == "nc_base":
            # nc_base 的 price 就是时间（小时）
            hours = float(item.get("price", 0))
            if min_num == "nc模板基本工时":
                nc_base_hours["template"] = hours
            elif min_num == "nc零件基本工时":
                nc_base_hours["component"] = hours
            else:
                logger.warning(
                    f"Unknown nc_base rule for min_num='{min_num}', price={item.get('price')}"
                )
    
    logger.info(f"NC base hours: {nc_base_hours}")
    
    return {
        "nc_base_hours": nc_base_hours
    }


def _get_template_threshold(rule_prices: List[Dict]) -> float:
    """
    获取模板零件判断标准（template_component）
    
    Returns:
        float: 阈值（mm），默认400
    """
    for item in rule_prices:
        if item.get("sub_category") == "template_component":
            return float(item.get("price", 400))
    
    return 400.0  # 默认值


def _determine_part_type(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    template_threshold: float
) -> Tuple[str, str]:
    """
    根据尺寸判断是模板还是零件
    
    规则：如果长宽厚任意一边大于阈值（默认400mm），则为模板
    
    Returns:
        (part_type, description)
        part_type: "template" 或 "component"
    """
    max_dimension = max(length_mm, width_mm, thickness_mm)
    
    if max_dimension > template_threshold:
        return "template", f"最大尺寸{max_dimension}mm > {template_threshold}mm，判定为模板"
    else:
        return "component", f"最大尺寸{max_dimension}mm <= {template_threshold}mm，判定为零件"


async def _calculate_part_nc_base_time(
    job_id: str,
    part: Dict,
    nc_base_config: Dict,
    template_threshold: float
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的NC基本时间
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    length_mm = part["length_mm"]
    width_mm = part["width_mm"]
    thickness_mm = part["thickness_mm"]
    nc_time_cost_data = part.get("nc_time_cost")
    
    logger.info(f"Calculating NC base time for part: {part_name} ({subgraph_id})")
    
    # 检查 nc_time_cost 数据
    if not nc_time_cost_data:
        logger.info(f"No nc_time_cost data for {part_name}, skipping NC base time calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "nc_base_cost": 0,
            "note": "nc_time_cost数据为空，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "nc_base_cost": 0,
            "calculation_steps": [{
                "step": "检查nc_time_cost",
                "note": "nc_time_cost数据为空，跳过NC基本时间计算"
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
                "nc_base_cost": 0,
                "note": f"nc_time_cost JSON解析失败: {e}"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "nc_base_cost": 0,
                "calculation_steps": [{
                    "step": "解析nc_time_cost",
                    "note": f"JSON解析失败: {e}，跳过NC基本时间计算"
                }]
            }
    
    calculation_steps = []
    
    # Step 1: 判断是模板还是零件
    part_type, part_type_desc = _determine_part_type(
        length_mm, width_mm, thickness_mm, template_threshold
    )
    
    calculation_steps.append({
        "step": "判断零件类型",
        "dimensions": {
            "length_mm": length_mm,
            "width_mm": width_mm,
            "thickness_mm": thickness_mm
        },
        "template_threshold": template_threshold,
        "part_type": part_type,
        "description": part_type_desc
    })
    
    # Step 2: 获取对应的nc_base时间
    nc_base_hours = nc_base_config["nc_base_hours"].get(part_type)
    
    if nc_base_hours is None:
        logger.warning(f"No nc_base hours found for part_type: {part_type}")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "nc_base_cost": 0,
            "note": f"未找到{part_type}的nc_base时间配置"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "nc_base_cost": 0,
            "calculation_steps": calculation_steps + [{
                "step": "错误",
                "note": f"未找到{part_type}的nc_base时间配置"
            }]
        }
    
    calculation_steps.append({
        "step": "获取nc_base时间",
        "part_type": part_type,
        "nc_base_hours": nc_base_hours,
        "note": "nc_base_cost字段存储的是时间（小时），不是费用"
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "part_type": part_type,
        "nc_base_cost": nc_base_hours
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "nc_base_cost": nc_base_hours,
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
        print("Usage: python price_nc_base.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    # 这里需要先调用检索脚本获取数据
    print("请通过 MCP 服务或 API 调用此计算脚本")
    print(f"job_id: {job_id}")
    print(f"subgraph_ids: {subgraph_ids}")
