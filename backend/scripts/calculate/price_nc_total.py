"""
NC总费用计算脚本
负责人：李志鹏

计算流程：
1. 调用 total_search 获取各面的NC时间和基本费用（nc_z_cost, nc_b_cost等和nc_base_cost）
2. 调用 nc_search 获取工时单价（work_hour: 60/80/100元/小时）
3. 调用 base_itemcode_search 获取零件尺寸和数量
4. 根据尺寸判断使用哪个工时单价（最短边和最长边判断）
5. 计算各面费用：时间 × 单价，得到 z_fee、b_fee 等
6. 比较各面费用与 nc_base_cost，取最大值
7. 乘以数量得到最终费用：nc_z_fee、nc_b_fee 等
8. 计算时间字段：各面时间 × 数量，得到 nc_z_time、nc_b_time 等
9. 更新 subgraphs 表的时间和费用字段
"""
from typing import List, Dict, Any, Tuple
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_nc_total_cost",
    "description": "计算NC总费用：根据各面时间和工时单价计算最终费用",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 total、nc 和 base_itemcode"
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
    "needs": ["total", "nc", "base_itemcode"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算NC总费用
    
    Args:
        search_data: 检索数据，包含 total、nc 和 base_itemcode
        job_id: 任务ID（可选）
        subgraph_ids: 子图ID列表（可选）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    total_data = search_data["total"]
    nc_data = search_data["nc"]
    base_data = search_data["base_itemcode"]
    
    # 提取 job_id
    if not job_id:
        job_id = total_data.get("job_id") or base_data.get("job_id")
    
    logger.info(f"Calculating NC total cost for job_id: {job_id}")
    
    # Step 1: 构建工时价格列表
    work_hour_prices = _build_work_hour_price_list(nc_data.get("nc_prices", []))
    
    if not work_hour_prices:
        logger.warning("No work_hour prices found")
        return {
            "job_id": job_id,
            "results": [],
            "message": "未找到工时价格数据"
        }
    
    # Step 2: 构建零件信息映射（subgraph_id -> part_info）
    part_info_map = {}
    for part in base_data.get("parts", []):
        part_info_map[part["subgraph_id"]] = {
            "length_mm": part["length_mm"],
            "width_mm": part["width_mm"],
            "thickness_mm": part["thickness_mm"],
            "quantity": part.get("quantity", 1)
        }
    
    # Step 3: 计算每个零件的NC总费用
    results = []
    db_updates = []
    
    for cost_detail in total_data.get("cost_details", []):
        subgraph_id = cost_detail["subgraph_id"]
        part_info = part_info_map.get(subgraph_id)
        
        if not part_info:
            logger.warning(f"No part info found for subgraph_id: {subgraph_id}")
            continue
        
        result, db_data = await _calculate_part_nc_total_cost(
            job_id, subgraph_id, cost_detail, part_info, work_hour_prices
        )
        results.append(result)
        if db_data:
            db_updates.append(db_data)
    
    # Step 4: 批量更新数据库
    if db_updates:
        await _batch_update_subgraphs(db_updates)
        
        # 更新 calculation_steps 到 processing_cost_calculation_details 表
        await _batch_update_calculation_steps(job_id, db_updates)
    
    logger.info(f"Completed NC total cost calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


def _build_work_hour_price_list(nc_prices: List[Dict]) -> List[Dict]:
    """
    构建工时价格列表
    
    Returns:
        [
            {
                "price": 60,
                "s_range": {"min": 0, "max": 800, "min_inclusive": False, "max_inclusive": False},
                "l_range": {"min": 0, "max": 1500, "min_inclusive": False, "max_inclusive": False}
            },
            ...
        ]
    """
    import re
    work_hour_prices = []
    
    for item in nc_prices:
        if item.get("sub_category") == "work_hour":
            price_value = float(item["price"])
            min_num = item.get("min_num", "")
            
            s_range = None
            l_range = None
            
            if min_num:
                # 提取 S 和 L 的区间
                s_match = re.search(r'S:\s*([\[\(])(\d+),\s*(\d+|[+∞∞]+)([\]\)])', str(min_num))
                l_match = re.search(r'L:\s*([\[\(])(\d+),\s*(\d+|[+∞∞]+)([\]\)])', str(min_num))
                
                if s_match:
                    s_min_bracket = s_match.group(1)
                    s_min = float(s_match.group(2))
                    s_max_str = s_match.group(3)
                    s_max_bracket = s_match.group(4)
                    
                    s_max = float('inf') if '+' in s_max_str or '∞' in s_max_str else float(s_max_str)
                    s_range = {
                        "min": s_min,
                        "max": s_max,
                        "min_inclusive": s_min_bracket == '[',
                        "max_inclusive": s_max_bracket == ']'
                    }
                
                if l_match:
                    l_min_bracket = l_match.group(1)
                    l_min = float(l_match.group(2))
                    l_max_str = l_match.group(3)
                    l_max_bracket = l_match.group(4)
                    
                    l_max = float('inf') if '+' in l_max_str or '∞' in l_max_str else float(l_max_str)
                    l_range = {
                        "min": l_min,
                        "max": l_max,
                        "min_inclusive": l_min_bracket == '[',
                        "max_inclusive": l_max_bracket == ']'
                    }
            
            work_hour_prices.append({
                "price": price_value,
                "s_range": s_range,
                "l_range": l_range,
                "min_num": min_num
            })
    
    # 按价格排序（从低到高）
    work_hour_prices.sort(key=lambda x: x["price"])
    
    logger.info(f"Found {len(work_hour_prices)} work_hour prices: {[p['price'] for p in work_hour_prices]}")
    
    return work_hour_prices


def _in_range(value: float, range_info: dict) -> bool:
    """判断值是否在区间内"""
    if not range_info:
        return False
    
    min_val = range_info["min"]
    max_val = range_info["max"]
    min_inclusive = range_info["min_inclusive"]
    max_inclusive = range_info["max_inclusive"]
    
    # 检查最小值
    if min_inclusive:
        if value < min_val:
            return False
    else:
        if value <= min_val:
            return False
    
    # 检查最大值
    if max_val == float('inf'):
        return True
    
    if max_inclusive:
        if value > max_val:
            return False
    else:
        if value >= max_val:
            return False
    
    return True


def _determine_work_hour_price(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    work_hour_prices: List[Dict]
) -> Tuple[float, str]:
    """
    根据尺寸动态判断使用哪个工时单价
    
    规则：
    - 尺寸排序后得到最长边(L)和最短边(S)
    - 遍历价格列表，找到同时满足 S 和 L 区间的价格
    - 如果某一边处于下一级，则价格就用下一级的
    - 如果多个价格都满足，使用价格最高的
    
    Returns:
        (price, description)
    """
    # 处理 None 值：如果尺寸为 None，使用 0
    safe_length = length_mm or 0
    safe_width = width_mm or 0
    safe_thickness = thickness_mm or 0
    
    # 排序尺寸
    dimensions = sorted([safe_length, safe_width, safe_thickness], reverse=True)
    longest = dimensions[0]
    shortest = dimensions[2]
    
    logger.info(f"Dimensions sorted: longest={longest:.2f}, shortest={shortest:.2f}")
    
    if not work_hour_prices:
        logger.error("No work_hour prices available")
        return 0, "无工时价格数据"
    
    # 从高价到低价遍历（因为已经按价格从低到高排序，所以反向遍历）
    matched_prices = []
    
    for price_info in work_hour_prices:
        s_range = price_info.get("s_range")
        l_range = price_info.get("l_range")
        
        # 检查是否同时满足 S 和 L 的区间条件
        s_match = _in_range(shortest, s_range) if s_range else True
        l_match = _in_range(longest, l_range) if l_range else True
        
        if s_match and l_match:
            matched_prices.append(price_info)
    
    # 如果有匹配的价格，使用价格最高的
    if matched_prices:
        # 按价格从高到低排序，取第一个
        matched_prices.sort(key=lambda x: x["price"], reverse=True)
        selected = matched_prices[0]
        
        price = selected["price"]
        s_range = selected.get("s_range")
        l_range = selected.get("l_range")
        
        # 构建描述
        reason_parts = []
        if s_range:
            s_bracket_left = '[' if s_range["min_inclusive"] else '('
            s_bracket_right = ']' if s_range["max_inclusive"] else ')'
            s_max_str = '+∞' if s_range["max"] == float('inf') else str(s_range["max"])
            reason_parts.append(f"最短边{shortest}mm在{s_bracket_left}{s_range['min']},{s_max_str}{s_bracket_right}")
        
        if l_range:
            l_bracket_left = '[' if l_range["min_inclusive"] else '('
            l_bracket_right = ']' if l_range["max_inclusive"] else ')'
            l_max_str = '+∞' if l_range["max"] == float('inf') else str(l_range["max"])
            reason_parts.append(f"最长边{longest}mm在{l_bracket_left}{l_range['min']},{l_max_str}{l_bracket_right}")
        
        reason = "，".join(reason_parts) if reason_parts else f"匹配到价格{price}"
        
        return price, f"{reason}，使用{price}元/小时"
    
    # 如果没有匹配的，使用最低价格作为默认值
    default_price = work_hour_prices[0]["price"]
    logger.warning(f"No matching price range for longest={longest}, shortest={shortest}, using default {default_price}")
    return default_price, f"未匹配到区间，使用默认{default_price}元/小时"


async def _calculate_part_nc_total_cost(
    job_id: str,
    subgraph_id: str,
    cost_detail: Dict,
    part_info: Dict,
    work_hour_prices: List[Dict]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的NC总费用
    
    Returns:
        tuple: (result_dict, db_update_dict)
    """
    # 获取数据
    nc_base_cost = cost_detail.get("nc_base_cost", 0)
    nc_z_cost = cost_detail.get("nc_z_cost", 0)
    nc_b_cost = cost_detail.get("nc_b_cost", 0)
    nc_c_cost = cost_detail.get("nc_c_cost", 0)
    nc_c_b_cost = cost_detail.get("nc_c_b_cost", 0)
    nc_z_view_cost = cost_detail.get("nc_z_view_cost", 0)
    nc_b_view_cost = cost_detail.get("nc_b_view_cost", 0)
    
    length_mm = part_info["length_mm"]
    width_mm = part_info["width_mm"]
    thickness_mm = part_info["thickness_mm"]
    quantity = part_info["quantity"]
    
    logger.info(f"Calculating NC total cost for subgraph_id: {subgraph_id}")
    
    # Step 1: 判断工时单价
    unit_price, price_reason = _determine_work_hour_price(
        length_mm, width_mm, thickness_mm, work_hour_prices
    )
    
    calculation_steps = []
    
    calculation_steps.append({
        "step": "判断工时单价",
        "dimensions": {
            "length_mm": length_mm,
            "width_mm": width_mm,
            "thickness_mm": thickness_mm
        },
        "unit_price": unit_price,
        "reason": price_reason
    })
    
    # Step 2: 与 nc_base_cost 比较时间，取最大值
    z_time = max(nc_z_cost, nc_base_cost) if nc_z_cost > 0 else 0
    b_time = max(nc_b_cost, nc_base_cost) if nc_b_cost > 0 else 0
    c_time = max(nc_c_cost, nc_base_cost) if nc_c_cost > 0 else 0
    c_b_time = max(nc_c_b_cost, nc_base_cost) if nc_c_b_cost > 0 else 0
    z_view_time = max(nc_z_view_cost, nc_base_cost) if nc_z_view_cost > 0 else 0
    b_view_time = max(nc_b_view_cost, nc_base_cost) if nc_b_view_cost > 0 else 0
    
    calculation_steps.append({
        "step": "与nc_base_cost比较时间取最大值",
        "nc_base_cost": nc_base_cost,
        "comparisons": {
            "z_time": {"nc_z_cost": nc_z_cost, "base": nc_base_cost, "max": z_time, "note": "为0则跳过比较" if nc_z_cost == 0 else f"max({nc_z_cost}, {nc_base_cost})"},
            "b_time": {"nc_b_cost": nc_b_cost, "base": nc_base_cost, "max": b_time, "note": "为0则跳过比较" if nc_b_cost == 0 else f"max({nc_b_cost}, {nc_base_cost})"},
            "c_time": {"nc_c_cost": nc_c_cost, "base": nc_base_cost, "max": c_time, "note": "为0则跳过比较" if nc_c_cost == 0 else f"max({nc_c_cost}, {nc_base_cost})"},
            "c_b_time": {"nc_c_b_cost": nc_c_b_cost, "base": nc_base_cost, "max": c_b_time, "note": "为0则跳过比较" if nc_c_b_cost == 0 else f"max({nc_c_b_cost}, {nc_base_cost})"},
            "z_view_time": {"nc_z_view_cost": nc_z_view_cost, "base": nc_base_cost, "max": z_view_time, "note": "为0则跳过比较" if nc_z_view_cost == 0 else f"max({nc_z_view_cost}, {nc_base_cost})"},
            "b_view_time": {"nc_b_view_cost": nc_b_view_cost, "base": nc_base_cost, "max": b_view_time, "note": "为0则跳过比较" if nc_b_view_cost == 0 else f"max({nc_b_view_cost}, {nc_base_cost})"}
        }
    })
    
    # Step 3: 乘以数量得到最终时间
    nc_z_time = round(z_time * quantity, 2)
    nc_b_time = round(b_time * quantity, 2)
    nc_c_time = round(c_time * quantity, 2)
    nc_c_b_time = round(c_b_time * quantity, 2)
    nc_z_view_time = round(z_view_time * quantity, 2)
    nc_b_view_time = round(b_view_time * quantity, 2)
    
    calculation_steps.append({
        "step": "乘以数量得到最终时间",
        "quantity": quantity,
        "final_times": {
            "nc_z_time": {"formula": f"{z_time} * {quantity} = {nc_z_time}", "value": nc_z_time},
            "nc_b_time": {"formula": f"{b_time} * {quantity} = {nc_b_time}", "value": nc_b_time},
            "nc_c_time": {"formula": f"{c_time} * {quantity} = {nc_c_time}", "value": nc_c_time},
            "nc_c_b_time": {"formula": f"{c_b_time} * {quantity} = {nc_c_b_time}", "value": nc_c_b_time},
            "nc_z_view_time": {"formula": f"{z_view_time} * {quantity} = {nc_z_view_time}", "value": nc_z_view_time},
            "nc_b_view_time": {"formula": f"{b_view_time} * {quantity} = {nc_b_view_time}", "value": nc_b_view_time}
        }
    })
    
    # Step 4: 计算费用（时间 × 单价 × 数量）
    nc_z_fee = round(z_time * unit_price * quantity, 2)
    nc_b_fee = round(b_time * unit_price * quantity, 2)
    nc_c_fee = round(c_time * unit_price * quantity, 2)
    nc_c_b_fee = round(c_b_time * unit_price * quantity, 2)
    nc_z_view_fee = round(z_view_time * unit_price * quantity, 2)
    nc_b_view_fee = round(b_view_time * unit_price * quantity, 2)
    
    calculation_steps.append({
        "step": "计算费用",
        "unit_price": unit_price,
        "quantity": quantity,
        "final_fees": {
            "nc_z_fee": {"formula": f"{z_time} * {unit_price} * {quantity} = {nc_z_fee}", "value": nc_z_fee},
            "nc_b_fee": {"formula": f"{b_time} * {unit_price} * {quantity} = {nc_b_fee}", "value": nc_b_fee},
            "nc_c_fee": {"formula": f"{c_time} * {unit_price} * {quantity} = {nc_c_fee}", "value": nc_c_fee},
            "nc_c_b_fee": {"formula": f"{c_b_time} * {unit_price} * {quantity} = {nc_c_b_fee}", "value": nc_c_b_fee},
            "nc_z_view_fee": {"formula": f"{z_view_time} * {unit_price} * {quantity} = {nc_z_view_fee}", "value": nc_z_view_fee},
            "nc_b_view_fee": {"formula": f"{b_view_time} * {unit_price} * {quantity} = {nc_b_view_fee}", "value": nc_b_view_fee}
        }
    })
    
    # 返回结果
    result = {
        "subgraph_id": subgraph_id,
        "quantity": quantity,
        "unit_price": unit_price,
        "fees": {
            "nc_z_fee": nc_z_fee,
            "nc_b_fee": nc_b_fee,
            "nc_c_fee": nc_c_fee,
            "nc_c_b_fee": nc_c_b_fee,
            "nc_z_view_fee": nc_z_view_fee,
            "nc_b_view_fee": nc_b_view_fee
        },
        "times": {
            "nc_z_time": nc_z_time,
            "nc_b_time": nc_b_time,
            "nc_c_time": nc_c_time,
            "nc_c_b_time": nc_c_b_time,
            "nc_z_view_time": nc_z_view_time,
            "nc_b_view_time": nc_b_view_time
        }
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "nc_z_time": nc_z_time,
        "nc_b_time": nc_b_time,
        "nc_c_time": nc_c_time,
        "nc_c_b_time": nc_c_b_time,
        "nc_z_view_time": nc_z_view_time,
        "nc_b_view_time": nc_b_view_time,
        "nc_z_fee": nc_z_fee,
        "nc_b_fee": nc_b_fee,
        "nc_c_fee": nc_c_fee,
        "nc_c_b_fee": nc_c_b_fee,
        "nc_z_view_fee": nc_z_view_fee,
        "nc_b_view_fee": nc_b_view_fee,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _batch_update_subgraphs(updates: List[Dict]):
    """批量更新 subgraphs 表"""
    logger.info(f"Batch updating {len(updates)} subgraphs records")
    
    sql = """
        UPDATE subgraphs
        SET 
            nc_z_time = $3::numeric,
            nc_b_time = $4::numeric,
            nc_c_time = $5::numeric,
            nc_c_b_time = $6::numeric,
            nc_z_view_time = $7::numeric,
            nc_b_view_time = $8::numeric,
            nc_z_fee = $9::numeric,
            nc_b_fee = $10::numeric,
            nc_c_fee = $11::numeric,
            nc_c_b_fee = $12::numeric,
            nc_z_view_fee = $13::numeric,
            nc_b_view_fee = $14::numeric
        WHERE job_id = $1::uuid AND subgraph_id = $2::text
    """
    
    tasks = []
    for data in updates:
        tasks.append(db.execute(
            sql,
            data["job_id"],
            data["subgraph_id"],
            data["nc_z_time"],
            data["nc_b_time"],
            data["nc_c_time"],
            data["nc_c_b_time"],
            data["nc_z_view_time"],
            data["nc_b_view_time"],
            data["nc_z_fee"],
            data["nc_b_fee"],
            data["nc_c_fee"],
            data["nc_c_b_fee"],
            data["nc_z_view_fee"],
            data["nc_b_view_fee"]
        ))
    
    try:
        await asyncio.gather(*tasks)
        logger.info(f"Successfully updated {len(updates)} subgraphs records")
    except Exception as e:
        logger.error(f"Batch update subgraphs failed: {e}")
        raise


async def _batch_update_calculation_steps(job_id: str, updates: List[Dict]):
    """批量更新 processing_cost_calculation_details 表的 calculation_steps"""
    logger.info(f"Batch updating calculation_steps for {len(updates)} records")
    
    try:
        from ._batch_update_helper import batch_upsert_with_steps
        
        # 为每个零件更新 calculation_steps（使用一个虚拟字段，只更新步骤）
        updates_for_batch = [
            {
                "job_id": job_id,
                "subgraph_id": d["subgraph_id"],
                "value": 0,  # 虚拟值，不会被使用
                "steps": d["calculation_steps"]
            }
            for d in updates
        ]
        
        # 使用 None 作为 field_name，表示只更新 calculation_steps
        await batch_upsert_with_steps(updates_for_batch, "nc_total", None)
        logger.info(f"Successfully updated calculation_steps for {len(updates)} records")
    
    except Exception as e:
        logger.error(f"Failed to update calculation_steps: {e}")
        # 不抛出异常，因为主要数据已经更新成功
        logger.warning("Calculation steps update failed, but main data is updated")


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
        print("Usage: python price_nc_total.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    
    print("请通过 MCP 服务或 API 调用此计算脚本")
    print(f"job_id: {job_id}")
    print(f"subgraph_ids: {subgraph_ids}")
