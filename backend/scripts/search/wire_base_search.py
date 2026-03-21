"""
线割工艺检索脚本
负责人：李志鹏

查询流程：
Step 1: job_price_snapshots表 -> 查询 category 为 wire 的 sub_category、price、unit、note
Step 2: job_price_snapshots表 -> 查询 category 为 rule 的 sub_category、price、unit
Step 3: 将 wire 工艺数据与价格数据进行匹配
注：查询时忽略 subgraph_id 字段，只根据 job_id 查询
注：sub_category 作为 conditions 字段使用
"""
from typing import List, Dict, Any
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "search_wire_by_job_id",
    "description": "按job_id查询线割工艺数据：从job_process_snapshots获取wire工艺，从job_price_snapshots获取wire/rule价格（注：subgraph_ids参数被忽略，因为线割工艺是全局配置）",
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
                "description": "此参数被忽略（为保持接口一致性）"
            }
        },
        "required": ["job_id", "subgraph_ids"]
    },
    "handler": "search_by_job_id"
}


async def search_by_job_id(job_id: str, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    """
    按job_id查询线割工艺和价格数据
    
    Args:
        job_id: 任务ID (UUID字符串)
        subgraph_ids: 此参数被忽略（为保持接口一致性，线割工艺是全局配置）
        
    Returns:
        Dict: {
            "wire_parts": [...],      # wire工艺零件（已匹配价格）
            "rule_prices": [...]      # rule价格列表
        }
    """
    # 注意：subgraph_ids 参数被忽略，因为线割工艺数据是全局配置，不按零件存储
    logger.info(f"Searching wire process info for job_id: {job_id} (subgraph_ids ignored)")
    
    # Step 1: 查询价格表 - category 为 wire、rule
    price_data = await _fetch_price_data(job_id)
    
    # 按 category 分组价格
    wire_prices = [p for p in price_data if p.get("category") == "wire"]
    rule_prices = [p for p in price_data if p.get("category") == "rule"]
    
    logger.info(f"Found {len(wire_prices)} wire prices, {len(rule_prices)} rule prices")
    
    # Step 2: 构建 wire_parts（从 wire_prices 中提取）
    wire_parts = []
    for price_info in wire_prices:
        sub_category = price_info.get("sub_category")
        note = price_info.get("note", sub_category)  # 如果没有 note，使用 sub_category
        
        wire_parts.append({
            "name": note,  # 使用 note 作为 name
            "conditions": sub_category,  # sub_category 作为 conditions
            "description": note,
            "price": price_info.get("price"),
            "unit": price_info.get("unit"),
            "min_num": price_info.get("min_num")
        })
    
    logger.info(f"Completed search, built {len(wire_parts)} wire parts")
    
    return {
        "data_type": "wire_base",
        "job_id": job_id,
        "wire_parts": wire_parts,
        "rule_prices": rule_prices
    }


async def _fetch_price_data(job_id: str) -> List[Dict]:
    """
    查询 job_price_snapshots 表
    条件: job_id + category IN ('wire', 'rule')
    获取: category, sub_category, price, unit, note, min_num
    注：忽略 subgraph_id 字段
    """
    sql = """
        SELECT DISTINCT category, sub_category, price, unit, note, min_num
        FROM job_price_snapshots
        WHERE job_id = $1::uuid AND category IN ('wire', 'rule')
    """
    try:
        rows = await db.fetch_all(sql, job_id)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Fetch price data failed: {e}")
        raise


# 便捷同步调用接口
def search_by_job_id_sync(job_id: str, subgraph_ids: List[str] = None) -> Dict[str, Any]:
    """同步版本的查询接口（subgraph_ids参数被忽略）"""
    return asyncio.run(search_by_job_id(job_id, subgraph_ids))


# 测试入口
if __name__ == "__main__":
    import sys
    import os
    
    # 添加项目根目录到Python路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python wire_base_search.py <job_id> [subgraph_ids...]")
        print("Note: subgraph_ids are ignored for wire search")
        sys.exit(1)
    
    job_id = sys.argv[1]
    results = search_by_job_id_sync(job_id)
    
    print(f"\n=== 查询结果 (job_id: {job_id}) ===")
    print(f"data_type: {results['data_type']}")
    
    print("\n--- Wire 零件 (已匹配价格) ---")
    if results["wire_parts"]:
        for r in results["wire_parts"]:
            print(f"  name: {r['name']}, conditions: {r['conditions']}, description: {r['description']}, price: {r['price']}, unit: {r['unit']}, min_num: {r.get('min_num', 'N/A')}")
    else:
        print("  (无数据)")
    
    print("\n--- Rule 价格列表 ---")
    for p in results["rule_prices"]:
        print(f"  sub_category: {p['sub_category']}, price: {p['price']}, unit: {p['unit']}, min_num: {p.get('min_num', 'N/A')}")
