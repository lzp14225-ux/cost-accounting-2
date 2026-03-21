"""
NC价格检索脚本
负责人：李志鹏

查询流程：
Step 1: job_price_snapshots表 -> 查询 category 为 NC 的 sub_category、price、unit
注：查询时忽略 subgraph_id 字段，只根据 job_id 查询
"""
from typing import List, Dict, Any
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)

# MCP 工具元数据
MCP_TOOL_META = {
    "name": "search_nc_by_job_id",
    "description": "按job_id查询NC价格数据：从job_price_snapshots获取NC价格（注：subgraph_ids参数被忽略，因为NC价格是全局配置）",
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
    按job_id查询NC价格数据
    
    Args:
        job_id: 任务ID (UUID字符串)
        subgraph_ids: 此参数被忽略（为保持接口一致性，NC价格是全局配置）
        
    Returns:
        Dict: {
            "nc_prices": [...]  # NC 价格列表
        }
    """
    # 注意：subgraph_ids 参数被忽略，因为NC价格数据是全局配置，不按零件存储
    logger.info(f"Searching NC price info for job_id: {job_id} (subgraph_ids ignored)")
    
    # Step 1: 查询价格表 - category 为 NC
    nc_prices = await _fetch_price_data(job_id)
    
    logger.info(f"Found {len(nc_prices)} NC prices")
    
    return {
        "data_type": "nc",
        "job_id": job_id,
        "nc_prices": nc_prices
    }


async def _fetch_price_data(job_id: str) -> List[Dict]:
    """
    Step 1: 查询 job_price_snapshots 表
    条件: job_id + category = 'NC' + sub_category IN ('nc_base', 'work_hour')
    获取: category, sub_category, price, unit, min_num
    注：忽略 subgraph_id 字段
    """
    sql = """
        SELECT DISTINCT category, sub_category, price, unit, min_num
        FROM job_price_snapshots
        WHERE job_id = $1::uuid AND category = 'NC' AND sub_category IN ('nc_base', 'work_hour')
    """
    try:
        rows = await db.fetch_all(sql, job_id)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Fetch NC price data failed: {e}")
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
        print("Usage: python nc_search.py <job_id> [subgraph_ids...]")
        print("Note: subgraph_ids are ignored for NC search")
        sys.exit(1)
    
    job_id = sys.argv[1]
    results = search_by_job_id_sync(job_id)
    
    print(f"\n=== 查询结果 (job_id: {job_id}) ===")
    print(f"data_type: {results['data_type']}")
    
    print("\n--- NC 价格列表 ---")
    for p in results["nc_prices"]:
        print(f"  sub_category: {p['sub_category']}, price: {p['price']}, unit: {p['unit']}, min_num: {p.get('min_num', 'N/A')}")
