import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from typing import List, Dict, Any, Optional
import logging
import asyncio

from api_gateway.database import db

logger = logging.getLogger(__name__)


async def match_and_update_process_rules(
    job_id: str,
    subgraph_ids: List[str]
) -> Dict[str, Any]:
    """
    匹配工艺规则并更新子图信息
    
    Args:
        job_id: 任务ID
        subgraph_ids: 子图ID列表
    
    Returns:
        {"status": "ok"} 或 {"status": "error", "message": "..."}
    """
    logger.info(f"[工艺规则匹配] 开始: job_id={job_id}, 子图数量={len(subgraph_ids)}")
    
    try:
        # 1. 查询子图信息
        subgraphs = await _fetch_subgraphs(job_id, subgraph_ids)
        if not subgraphs:
            logger.warning(f"[工艺规则匹配] 未找到子图数据")
            return {"status": "ok"}
        
        # 2. 查询工艺规则
        rules_map = await _fetch_process_rules()
        
        # 3. 并发处理每个子图
        tasks = [
            _process_single_subgraph(sg, rules_map)
            for sg in subgraphs
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"[工艺规则匹配] 完成")
        return {"status": "ok"}
    
    except Exception as e:
        logger.error(f"[工艺规则匹配] 失败: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _fetch_subgraphs(job_id: str, subgraph_ids: List[str]) -> List[Dict]:
    """查询子图信息"""
    sql = """
        SELECT subgraph_id, part_name, wire_process_note, wire_process
        FROM subgraphs
        WHERE job_id = $1::uuid AND subgraph_id = ANY($2)
    """
    try:
        rows = await db.fetch_all(sql, job_id, subgraph_ids)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"[查询子图] 失败: {e}")
        raise


async def _fetch_process_rules() -> Dict[str, Dict]:
    """查询所有工艺规则，返回 {part_name: {description, conditions}}"""
    sql = """
        SELECT name, description, conditions
        FROM process_rules
    """
    try:
        rows = await db.fetch_all(sql)
        return {
            row["name"]: {
                "description": row["description"],
                "conditions": row["conditions"]
            }
            for row in rows
        }
    except Exception as e:
        logger.error(f"[查询规则] 失败: {e}")
        return {}


async def _process_single_subgraph(subgraph: Dict, rules_map: Dict):
    """处理单个子图"""
    # 任一字段有值就跳过
    if subgraph["wire_process_note"] or subgraph["wire_process"]:
        logger.debug(f"[跳过] {subgraph['part_name']}: 已有工艺信息")
        return
    
    # 查找匹配的规则
    rule = rules_map.get(subgraph["part_name"])
    if not rule:
        logger.debug(f"[未匹配] {subgraph['part_name']}: 未找到规则")
        return
    
    # 更新
    try:
        await _update_subgraph_process(
            subgraph["subgraph_id"],
            rule["description"],
            rule["conditions"]
        )
        logger.info(
            f"[更新成功] {subgraph['part_name']} -> "
            f"note={rule['description']}, process={rule['conditions']}"
        )
    except Exception as e:
        logger.error(f"[更新失败] {subgraph['part_name']}: {e}")


async def _update_subgraph_process(
    subgraph_id: str,
    wire_process_note: Optional[str],
    wire_process: Optional[str]
):
    """更新子图的工艺信息"""
    sql = """
        UPDATE subgraphs
        SET wire_process_note = $1, wire_process = $2, updated_at = NOW()
        WHERE subgraph_id = $3
    """
    await db.execute(sql, wire_process_note, wire_process, subgraph_id)


# 测试入口
if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    async def test():
        if len(sys.argv) < 3:
            print("用法: python process_rule_matcher.py <job_id> <subgraph_id1> [subgraph_id2] ...")
            sys.exit(1)
        
        job_id = sys.argv[1]
        subgraph_ids = sys.argv[2:]
        
        result = await match_and_update_process_rules(job_id, subgraph_ids)
        print(f"\n结果: {result}")
    
    asyncio.run(test())
