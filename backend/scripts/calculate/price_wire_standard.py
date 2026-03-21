"""
线割标准基本费计算脚本
负责人：李志鹏

计算流程：
1. 调用 base_itemcode_search 获取零件基础信息（wire_process_note, wire_process, boring_num, quantity）
2. 调用 wire_standard_search 获取标准价格信息（base_fee, boring_fee）
3. 根据 wire_process 匹配 sub_category 获取价格
   - slow_and_one（慢丝割一修一）-> 慢丝
   - slow_and_two（慢丝割一修二）-> 慢丝
   - medium（中丝）-> 中丝
   - fast（快丝）-> 快丝
4. 计算公式：
   - 慢丝：standard_base_cost = boring_num × boring_fee
   - 中丝/快丝：standard_base_cost = (boring_num × boring_fee) + (数量 × base_fee)
5. 更新 processing_cost_calculation_details 表的 standard_base_cost 字段和步骤字段
"""
from typing import List, Dict, Any
import logging
import asyncio
import json

from api_gateway.database import db
from ._batch_update_helper import batch_upsert_with_steps

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "calculate_wire_standard_price",
    "description": "计算线割标准基本费：根据零件信息和标准价格计算费用",
    "inputSchema": {
        "type": "object",
        "properties": {
            "search_data": {
                "type": "object",
                "description": "检索数据，包含 base_itemcode 和 wire_standard"
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
    "needs": ["base_itemcode", "wire_standard"]
}


async def calculate(
    search_data: Dict[str, Any],
    job_id: str = None,
    subgraph_ids: List[str] = None
) -> Dict[str, Any]:
    """
    计算线割标准基本费
    
    Args:
        search_data: 检索数据，包含 base_itemcode 和 wire_standard
        job_id: 任务ID（可选，用于日志和数据库更新）
        subgraph_ids: 子图ID列表（可选，用于过滤）
        
    Returns:
        Dict: 计算结果
    """
    # 获取检索数据
    base_data = search_data["base_itemcode"]
    wire_standard_data = search_data["wire_standard"]
    
    # 提取 job_id（如果未传入）
    if not job_id:
        job_id = base_data.get("job_id")
    
    logger.info(f"Calculating wire standard price for job_id: {job_id}, parts count: {len(base_data.get('parts', []))}")
    
    # Step 3: 构建价格映射 (sub_category -> {price, unit})
    price_map = {}
    for price_item in wire_standard_data.get("base_prices", []):
        sub_category = price_item.get("sub_category")
        price_map[sub_category] = {
            "price": float(price_item.get("price", 0)),
            "unit": price_item.get("unit", "")
        }
    
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
                "value": d["standard_base_cost"],
                "steps": d["calculation_steps"]
            }
            for d in db_updates
        ]
        await batch_upsert_with_steps(updates_for_batch, "wire_standard", "standard_base_cost")
    
    logger.info(f"Completed calculation for {len(results)} parts")
    
    return {
        "job_id": job_id,
        "results": results
    }


async def _calculate_part_price(
    job_id: str,
    part: Dict,
    price_map: Dict
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    计算单个零件的线割标准基本费
    """
    subgraph_id = part["subgraph_id"]
    part_name = part["part_name"]
    wire_process_note = part.get("wire_process_note")  # 例如: 慢丝割一修一
    wire_process = part.get("wire_process")  # 例如: slow_and_one
    boring_num = part.get("boring_num", 0)  # 孔数
    quantity = part.get("quantity", 1)  # 数量
    metadata = part.get("metadata")  # 获取 metadata 用于检查
    
    logger.info(f"Calculating price for part: {part_name} ({subgraph_id}), wire_process: {wire_process}, boring_num: {boring_num}")
    
    # 检查 metadata（与 price_wire_base.py 保持一致）
    if not metadata:
        logger.info(f"No metadata for {part_name}, skipping wire_standard calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "standard_base_cost": 0,
            "note": "metadata为空，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "standard_base_cost": 0,
            "calculation_steps": [{
                "step": "检查metadata",
                "note": "metadata为空，跳过线割标准基本费计算"
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
                "standard_base_cost": 0,
                "note": f"metadata JSON解析失败，跳过计算"
            }, {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "standard_base_cost": 0,
                "calculation_steps": [{
                    "step": "解析metadata",
                    "note": f"JSON解析失败: {e}，跳过线割标准基本费计算"
                }]
            }
    
    # 确保 metadata 是字典类型
    if not isinstance(metadata, dict):
        logger.info(f"metadata is not a dict for {part_name}, skipping calculation")
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "standard_base_cost": 0,
            "note": "metadata类型错误，跳过计算"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "standard_base_cost": 0,
            "calculation_steps": [{
                "step": "检查metadata类型",
                "note": "metadata不是字典类型，跳过线割标准基本费计算"
            }]
        }
    
    # 根据 wire_process 匹配 sub_category
    if not wire_process:
        logger.warning(f"wire_process is empty for part: {part_name}, skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "数据验证",
            "status": "failed",
            "reason": "wire_process为空",
            "standard_base_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "standard_base_cost": 0.0,
            "note": "wire_process为空"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "standard_base_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    # 获取对应的价格信息
    price_info = price_map.get(wire_process)
    if not price_info:
        logger.warning(f"No price found for wire_process: {wire_process}, skipping calculation")
        
        # 返回 0 并写入数据库
        calculation_steps = [{
            "step": "匹配工艺",
            "status": "failed",
            "wire_process": wire_process,
            "reason": f"未找到wire_process对应的价格: {wire_process}",
            "standard_base_cost": 0.0
        }]
        
        return {
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "wire_process": wire_process,
            "standard_base_cost": 0.0,
            "note": f"未找到wire_process对应的价格: {wire_process}"
        }, {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "standard_base_cost": 0.0,
            "calculation_steps": calculation_steps
        }
    
    unit_price = price_info["price"]
    unit = price_info["unit"]
    
    # 计算孔类费：boring_num * price
    hole_cost = boring_num * unit_price
    
    # 判断是否是中丝或快丝，需要加基本费（慢丝不加基本费）
    base_fee = 0
    base_fee_desc = ""
    wire_type = ""
    
    # 确保 wire_process_note 不为 None
    wire_process_note_str = wire_process_note or ""
    
    if "middle" in wire_process or "中丝" in wire_process_note_str:
        wire_type = "middle"
        middle_base_fee_info = price_map.get("中丝基本费", {})
        if middle_base_fee_info:
            base_fee = quantity * middle_base_fee_info.get("price", 0)
            base_fee_desc = f"中丝基本费: {quantity} * {middle_base_fee_info.get('price', 0)} = {base_fee}"
    elif "fast" in wire_process or "快丝" in wire_process_note_str:
        wire_type = "fast"
        fast_base_fee_info = price_map.get("快丝基本费", {})
        if fast_base_fee_info:
            base_fee = quantity * fast_base_fee_info.get("price", 0)
            base_fee_desc = f"快丝基本费: {quantity} * {fast_base_fee_info.get('price', 0)} = {base_fee}"
    elif "slow" in wire_process or "慢丝" in wire_process_note_str:
        wire_type = "slow"
        # 慢丝不加基本费
        base_fee = 0
        base_fee_desc = "慢丝不需要基本费"
    
    # 计算总费用
    standard_base_cost = hole_cost + base_fee
    
    # 构建计算步骤
    calculation_steps = [
        {
            "step": "匹配工艺",
            "wire_process_note": wire_process_note,
            "wire_process": wire_process,
            "wire_type": wire_type,
            "matched_sub_category": wire_process,
            "unit_price": unit_price,
            "unit": unit
        },
        {
            "step": "计算孔类费",
            "formula": f"{boring_num} * {unit_price}",
            "boring_num": boring_num,
            "unit_price": unit_price,
            "hole_cost": round(hole_cost, 4)
        }
    ]
    
    if base_fee > 0:
        calculation_steps.append({
            "step": "计算基本费",
            "description": base_fee_desc,
            "quantity": quantity,
            "base_fee": round(base_fee, 4)
        })
    
    calculation_steps.append({
        "step": "计算总费用",
        "formula": f"孔类费 + 基本费 = {round(hole_cost, 4)} + {round(base_fee, 4)}",
        "standard_base_cost": round(standard_base_cost, 4)
    })
    
    # 返回结果和数据库更新数据
    result = {
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "wire_process_note": wire_process_note,
        "wire_process": wire_process,
        "wire_type": wire_type,
        "boring_num": boring_num,
        "quantity": quantity,
        "hole_cost": round(hole_cost, 4),
        "base_fee": round(base_fee, 4),
        "standard_base_cost": round(standard_base_cost, 4)
    }
    
    db_data = {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "standard_base_cost": standard_base_cost,
        "calculation_steps": calculation_steps
    }
    
    return result, db_data


async def _update_calculation_details(
    job_id: str,
    subgraph_id: str,
    standard_base_cost: float,
    new_steps: List[Dict]
):
    """
    更新 processing_cost_calculation_details 表（保留用于向后兼容）
    """
    await batch_upsert_with_steps(
        [{
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "value": standard_base_cost,
            "steps": new_steps
        }],
        "wire_standard",
        "standard_base_cost"
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
        print("Usage: python price_wire_standard.py <job_id> <subgraph_id1> [subgraph_id2 ...]")
        sys.exit(1)
    
    job_id = sys.argv[1]
    subgraph_ids = sys.argv[2:]
    results = calculate_by_job_id_sync(job_id, subgraph_ids)
    
    print(f"\n=== 计算结果 (job_id: {job_id}) ===")
    for result in results["results"]:
        if "error" in result:
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  错误: {result['error']}")
        else:
            print(f"\n零件: {result['part_name']} ({result['subgraph_id']})")
            print(f"  工艺说明: {result['wire_process_note']}")
            print(f"  工艺代码: {result['wire_process']}")
            print(f"  线割类型: {result['wire_type']}")
            print(f"  孔数: {result['boring_num']}")
            print(f"  数量: {result['quantity']}")
            print(f"  孔类费: {result['hole_cost']} 元")
            print(f"  基本费: {result['base_fee']} 元")
            print(f"  标准基本费: {result['standard_base_cost']} 元")
