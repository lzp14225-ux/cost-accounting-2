"""
牙孔/螺丝费用计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（tooth_hole）
2. 调用 tooth_hole_search 获取价格信息
3. 根据 is_through 判断通孔/盲孔
4. 根据 size 计算放电时间和费用
5. 根据 set_screw 判断使用 screw 还是 stop_screw 价格
6. 计算周长（仅通孔）
7. 更新 processing_cost_calculation_details 表
"""
from typing import List, Dict, Any
import logging
import asyncio
import json
import math

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_tooth_hole_cost",
    "description": "计算牙孔/螺丝费用：根据孔类型、尺寸计算放电费用和周长",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 tooth_hole"
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
    "needs": ["base_itemcode", "tooth_hole"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算牙孔/螺丝费用
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 tooth_hole
        job_id: 任务ID（可选）
        subgraph_ids: 子图ID列表（可选）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    tooth_hole_data = search_data["tooth_hole"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating tooth hole cost for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # 构建价格映射
    price_map = _build_price_map(tooth_hole_data)
    
    # 计算每个零件的费用
    results = []
    db_updates_cost = []
    db_updates_time = []
    
    for part in base_data["parts"]:
        result, db_data_cost, db_data_time = await _calculate_part_cost(
            job_id, part, price_map
        )
        results.append(result)
        if db_data_cost:
            db_updates_cost.append(db_data_cost)
        if db_data_time:
            db_updates_time.append(db_data_time)
    
    # 批量写入数据库 - tooth_hole_cost
    if db_updates_cost:
        updates_for_batch = [
            {
                "job_id": d["job_id"],
                "subgraph_id": d["subgraph_id"],
                "value": d["tooth_hole_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates_cost
        ]
        await batch_upsert_with_steps(updates_for_batch, "tooth_hole", "tooth_hole_cost")
    
    # 批量写入数据库 - tooth_hole_time_cost
    if db_updates_time:
        updates_for_batch = [
            {
                "job_id": d["job_id"],
                "subgraph_id": d["subgraph_id"],
                "value": d["tooth_hole_time_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates_time
        ]
        await batch_upsert_with_steps(updates_for_batch, "tooth_hole_time", "tooth_hole_time_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_price_map(tooth_hole_data: Dict) -> Dict[str, Any]:
    """
    构建价格映射，从 min_num 字段动态解析条件
    
    Returns:
        {
            "through_hole": [
                {"time": 0.2, "unit": "小时", "condition": "<", "threshold": 10},
                {"time": 0.3, "unit": "小时", "condition": ">=", "threshold": 10},
                {"hourly_rate": 50, "unit": "元/小时"}
            ],
            "blind_hole": [
                {"time": 0.3, "unit": "小时", "condition": "<", "threshold": 10},
                {"time": 0.4, "unit": "小时", "condition": ">=", "threshold": 10},
                {"hourly_rate": 50, "unit": "元/小时"}
            ],
            "screw": {"M8": 6.806, "M10": 8.506, ...},
            "stop_screw": {"M12": 10.505, ...}
        }
    """
    import re
    price_map = {
        "through_hole": [],
        "blind_hole": [],
        "screw": {},
        "stop_screw": {}
    }
    
    # 处理 tooth_hole 价格
    for price in tooth_hole_data.get("tooth_hole_prices", []):
        sub_category = price.get("sub_category")
        price_value = float(price.get("price", 0))
        unit = price.get("unit", "")
        min_num = price.get("min_num", "")
        
        if sub_category in ["through_hole", "blind_hole"]:
            if "元/小时" in unit:
                # 这是小时费率
                price_map[sub_category].append({
                    "hourly_rate": price_value,
                    "unit": unit
                })
            elif "小时" in unit:
                # 这是时间，解析 min_num 条件
                # 格式: "<M10" 或 ">=M10" 或 "None"
                if min_num and min_num != "None":
                    # 匹配格式: <M10 或 >=M10
                    match = re.match(r'([<>=]+)M(\d+)', str(min_num))
                    if match:
                        condition = match.group(1)
                        threshold = int(match.group(2))
                        
                        price_map[sub_category].append({
                            "time": price_value,
                            "unit": unit,
                            "condition": condition,
                            "threshold": threshold
                        })
                    else:
                        logger.warning(f"Failed to parse min_num format: {min_num}")
                else:
                    # min_num 为 None，无条件
                    price_map[sub_category].append({
                        "time": price_value,
                        "unit": unit,
                        "condition": None,
                        "threshold": None
                    })
    
    # 处理 screw 价格
    for price in tooth_hole_data.get("screw_prices", []):
        sub_category = price.get("sub_category")
        price_value = float(price.get("price", 0))
        price_map["screw"][sub_category] = price_value
    
    # 处理 stop_screw 价格
    for price in tooth_hole_data.get("stop_screw_prices", []):
        sub_category = price.get("sub_category")
        price_value = float(price.get("price", 0))
        price_map["stop_screw"][sub_category] = price_value
    
    return price_map


def _extract_size_number(size: str) -> int:
    """
    从 size 字符串中提取数字
    例如: "M8" -> 8, "M12" -> 12
    """
    try:
        return int(size.replace("M", "").replace("m", ""))
    except:
        return 0


async def _calculate_part_cost(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的牙孔/螺丝费用
    
    Returns:
        tuple: (result_dict, db_update_dict_cost, db_update_dict_time)
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    tooth_hole = part.get("tooth_hole")
    
    logger.info(f"Calculating tooth hole cost for part: {part_name} ({subgraph_id})")
    
    # 解析 tooth_hole
    if isinstance(tooth_hole, str):
        try:
            tooth_hole = json.loads(tooth_hole)
        except Exception as e:
            logger.error(f"Failed to parse tooth_hole JSON: {e}")
            tooth_hole = {}
    
    # 如果没有牙孔数据，返回空结果
    if not tooth_hole or "tooth_hole_details" not in tooth_hole:
        logger.info(f"No tooth_hole data for part: {part_name}")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "tooth_hole_cost": 0,
            "tooth_hole_time_cost": 0,
            "total_perimeter": 0
        }, None, None
    
    tooth_hole_details = tooth_hole.get("tooth_hole_details", [])
    
    # 计算步骤
    calculation_steps = []
    total_discharge_cost = 0  # 放电费用（元）
    total_discharge_time = 0  # 放电时间（小时）
    total_perimeter = 0
    perimeter_by_view = {}  # 按视图分组的周长
    
    for detail in tooth_hole_details:
        code = detail.get("code")
        size = detail.get("size")
        number = detail.get("number", 0)
        is_through = detail.get("is_through") == "t"
        set_screw = detail.get("set_screw") == "t"
        view = detail.get("view", "top_view")  # 获取视图信息
        
        # Step 1: 判断孔类型
        hole_type = "通孔" if is_through else "盲孔"
        calculation_steps.append({
            "step": "判断孔类型",
            "code": code,
            "size": size,
            "number": number,
            "is_through": is_through,
            "hole_type": hole_type,
            "set_screw": set_screw
        })
        
        # Step 2: 计算放电时间和费用
        size_number = _extract_size_number(size)
        
        # 动态获取时间和费率
        hole_category = "through_hole" if is_through else "blind_hole"
        time_per_hole = 0
        hourly_rate = 0
        matched_condition = None
        
        # 先查找小时费率（避免被 break 跳过）
        for rule in price_map[hole_category]:
            if "hourly_rate" in rule:
                hourly_rate = rule["hourly_rate"]
                break
        
        # 再查找匹配的时间规则
        for rule in price_map[hole_category]:
            if "time" in rule:
                condition = rule.get("condition")
                threshold = rule.get("threshold")
                
                if condition is None:
                    # 无条件，作为默认值
                    if time_per_hole == 0:
                        time_per_hole = rule["time"]
                        matched_condition = "默认"
                elif condition == "<":
                    if size_number < threshold:
                        time_per_hole = rule["time"]
                        matched_condition = f"<M{threshold}"
                        break
                elif condition == ">=":
                    if size_number >= threshold:
                        time_per_hole = rule["time"]
                        matched_condition = f">=M{threshold}"
                        break
                elif condition == "<=":
                    if size_number <= threshold:
                        time_per_hole = rule["time"]
                        matched_condition = f"<=M{threshold}"
                        break
                elif condition == ">":
                    if size_number > threshold:
                        time_per_hole = rule["time"]
                        matched_condition = f">M{threshold}"
                        break
        
        if time_per_hole == 0:
            logger.warning(f"No matching time rule for {hole_category}, size_number={size_number}")
        
        if hourly_rate == 0:
            logger.warning(f"No hourly_rate found for {hole_category}")
        
        # 计算总时间和费用
        total_time = number * time_per_hole  # 小时
        discharge_cost = total_time * hourly_rate  # 元
        total_discharge_time += total_time
        total_discharge_cost += discharge_cost
        
        calculation_steps.append({
            "step": "计算放电时间和费用",
            "size": size,
            "size_number": size_number,
            "matched_condition": matched_condition,
            "time_per_hole": time_per_hole,
            "number": number,
            "total_time": round(total_time, 4),  # 小时，保留4位小数
            "hourly_rate": hourly_rate,
            "discharge_cost": round(discharge_cost, 2),  # 元，保留2位小数
            "formula": f"{number} × {time_per_hole}小时 × {hourly_rate}元/小时 = {round(discharge_cost, 2)}元"
        })
        
        # Step 3: 计算周长（仅通孔）
        if is_through:
            # 根据 set_screw 选择价格表
            if set_screw:
                diameter = price_map["stop_screw"].get(size, 0)
                price_source = "stop_screw"
            else:
                diameter = price_map["screw"].get(size, 0)
                price_source = "screw"
            
            # 计算周长 C = π × d × number
            perimeter = math.pi * diameter * number
            total_perimeter += perimeter
            
            # 按视图分组周长
            if view not in perimeter_by_view:
                perimeter_by_view[view] = 0
            perimeter_by_view[view] += perimeter
            
            calculation_steps.append({
                "step": "计算周长（通孔）",
                "view": view,
                "size": size,
                "diameter": diameter,
                "number": number,
                "perimeter": round(perimeter, 2),
                "price_source": price_source,
                "formula": f"π × {diameter} × {number} = {round(perimeter, 2)}"
            })
        else:
            calculation_steps.append({
                "step": "盲孔无需计算周长",
                "note": "盲孔不计算周长"
            })
    
    # 汇总
    calculation_steps.append({
        "step": "费用和时间汇总",
        "total_discharge_time": round(total_discharge_time, 4),  # 小时
        "total_discharge_cost": round(total_discharge_cost, 2),  # 元
        "total_perimeter": round(total_perimeter, 2),  # mm
        "perimeter_by_view": {k: round(v, 2) for k, v in perimeter_by_view.items()}
    })
    
    # 返回结果
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "tooth_hole_cost": round(total_discharge_cost, 2),  # 放电费用（元）
        "tooth_hole_time_cost": round(total_discharge_time, 4),  # 放电时间（小时）
        "total_perimeter": round(total_perimeter, 2),
        "perimeter_by_view": {k: round(v, 2) for k, v in perimeter_by_view.items()}
    }
    
    # 数据库更新数据 - tooth_hole_cost (放电费用，元)
    db_data_cost = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "tooth_hole_cost": total_discharge_cost,
        "calculation_steps": calculation_steps
    }
    
    # 数据库更新数据 - tooth_hole_time_cost (放电时间，小时)
    db_data_time = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "tooth_hole_time_cost": total_discharge_time,
        "calculation_steps": []  # 时间字段不需要重复存储步骤
    }
    
    logger.info(
        f"[{subgraph_id}] {part_name}: tooth_hole_cost={total_discharge_cost:.2f}元, "
        f"tooth_hole_time_cost={total_discharge_time:.4f}小时, "
        f"total_perimeter={total_perimeter:.2f}mm"
    )
    
    return result, db_data_cost, db_data_time


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
    
    print("price_tooth_hole.py - 牙孔/螺丝费用计算脚本")
    print("需要配合 base_itemcode_search.py 和 tooth_hole_search.py 使用")
    print("\n使用方式：")
    print("1. 先执行 base_itemcode_search.py 获取零件信息")
    print("2. 再执行 tooth_hole_search.py 获取价格信息")
    print("3. 最后调用本脚本计算费用并更新数据库")
