"""
排除零件清理工具
特征识别完成后自动调用，根据两层过滤逻辑将不需要参与报价的零件从数据库中删除。

过滤规则（与报表导出一致）：
  第一层：subgraphs.part_name 模糊匹配关键字
  第二层：features.processing_instructions 递归展平后模糊匹配关键字

级联删除顺序（外键约束）：
  1. processing_cost_calculation_details
  2. features
  3. subgraphs
"""

import asyncio
import logging
from typing import Dict, Any, List, Set

from api_gateway.database import db

logger = logging.getLogger(__name__)

# 排除关键字（与 reports.py / price_total.py 保持一致）
EXCLUDE_KEYWORDS = ["订购", "附图订购", "二次加工", "钣金"]


# ============================================================================
# 公开接口
# ============================================================================

async def clean_excluded_parts(job_id: str) -> Dict[str, Any]:
    """
    清理指定任务中需要排除的零件。

    在特征识别完成后调用：
    1. 查询该 job 下所有 subgraphs + features
    2. 按两层过滤逻辑判断哪些需要删除
    3. 按外键顺序级联删除

    Args:
        job_id: 任务 ID (UUID 字符串)

    Returns:
        {
            "status": "ok",
            "job_id": "...",
            "total_subgraphs": 100,
            "excluded_count": 5,
            "remaining_count": 95,
            "excluded_subgraph_ids": ["...", ...],
            "deleted_tables": {
                "processing_cost_calculation_details": 5,
                "features": 5,
                "subgraphs": 5
            }
        }
    """
    logger.info(f"[排除零件清理] 开始: job_id={job_id}")

    try:
        # 1. 查询所有子图及其特征
        rows = await _fetch_subgraphs_with_features(job_id)
        total_count = len(rows)

        if total_count == 0:
            logger.info(f"[排除零件清理] 未找到子图，跳过: job_id={job_id}")
            return _build_result(job_id, 0, 0, [], {})

        # 2. 批量并发判断哪些需要排除
        tasks = [
            _should_exclude(row)
            for row in rows
        ]
        decisions = await asyncio.gather(*tasks)

        # 3. 收集需要删除的 subgraph_id
        excluded_ids: List[str] = []
        for row, should_exclude in zip(rows, decisions):
            if should_exclude:
                sid = str(row["subgraph_id"])
                excluded_ids.append(sid)

        excluded_count = len(excluded_ids)
        remaining_count = total_count - excluded_count

        if excluded_count == 0:
            logger.info(
                f"[排除零件清理] 完成: 无需删除 "
                f"(共 {total_count} 个子图, job_id={job_id})"
            )
            return _build_result(job_id, total_count, 0, [], {})

        logger.info(
            f"[排除零件清理] 发现 {excluded_count} 个需排除的子图: "
            f"{excluded_ids}"
        )

        # 4. 级联删除
        deleted_counts = await _cascade_delete(job_id, excluded_ids)

        # 5. 更新 jobs.total_subgraphs
        await _update_job_subgraph_count(job_id, remaining_count)

        logger.info(
            f"[排除零件清理] 完成: 删除 {excluded_count} 个, "
            f"保留 {remaining_count} 个 (job_id={job_id})"
        )

        return _build_result(
            job_id, total_count, excluded_count,
            excluded_ids, deleted_counts
        )

    except Exception as e:
        logger.error(
            f"[排除零件清理] 执行失败: job_id={job_id}, error={e}",
            exc_info=True
        )
        return {
            "status": "error",
            "job_id": job_id,
            "message": f"清理失败: {str(e)}"
        }


# ============================================================================
# 内部函数 — 数据查询
# ============================================================================

async def _fetch_subgraphs_with_features(job_id: str) -> List[Dict[str, Any]]:
    """查询子图及其对应的特征数据（LEFT JOIN，一次查回）。"""
    sql = """
        SELECT
            s.subgraph_id,
            s.part_name,
            f.processing_instructions
        FROM subgraphs s
        LEFT JOIN features f
            ON s.job_id = f.job_id AND s.subgraph_id = f.subgraph_id
        WHERE s.job_id = $1::uuid
    """
    return await db.fetch_all(sql, job_id)


# ============================================================================
# 内部函数 — 过滤判断
# ============================================================================

async def _should_exclude(row: Dict[str, Any]) -> bool:
    """
    两层判断逻辑（与 reports.py 保持一致）：
    1. 先看 part_name
    2. 再看 processing_instructions
    """
    # 第一层：零件名称
    part_name = str(row.get("part_name") or "").strip()
    if _contains_exclude_keyword(part_name):
        return True

    # 第二层：加工说明
    processing_text = _flatten_processing_instructions(
        row.get("processing_instructions")
    )
    return _contains_exclude_keyword(processing_text)


def _contains_exclude_keyword(text: str) -> bool:
    """模糊匹配排除关键字。"""
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in EXCLUDE_KEYWORDS)


def _flatten_processing_instructions(value) -> str:
    """将 processing_instructions（可能是 dict/list/str）递归展平为纯字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            _flatten_processing_instructions(item)
            for item in value.values()
        )
    if isinstance(value, (list, tuple, set)):
        return " ".join(
            _flatten_processing_instructions(item)
            for item in value
        )
    return str(value)


# ============================================================================
# 内部函数 — 级联删除
# ============================================================================

async def _cascade_delete(
    job_id: str,
    subgraph_ids: List[str]
) -> Dict[str, int]:
    """
    按外键约束顺序级联删除 3 张表的数据。

    删除顺序：
    1. processing_cost_calculation_details（子表）
    2. features（子表）
    3. subgraphs（主表）
    """
    deleted = {}

    # 1. 删除 processing_cost_calculation_details
    sql_pccd = """
        DELETE FROM processing_cost_calculation_details
        WHERE job_id = $1::uuid
          AND subgraph_id = ANY($2::text[])
    """
    result = await db.execute(sql_pccd, job_id, subgraph_ids)
    deleted["processing_cost_calculation_details"] = _parse_delete_count(result)
    logger.info(
        f"[排除零件清理] 删除 processing_cost_calculation_details: "
        f"{deleted['processing_cost_calculation_details']} 条"
    )

    # 2. 删除 features
    sql_features = """
        DELETE FROM features
        WHERE job_id = $1::uuid
          AND subgraph_id = ANY($2::text[])
    """
    result = await db.execute(sql_features, job_id, subgraph_ids)
    deleted["features"] = _parse_delete_count(result)
    logger.info(
        f"[排除零件清理] 删除 features: {deleted['features']} 条"
    )

    # 3. 删除 subgraphs
    sql_subgraphs = """
        DELETE FROM subgraphs
        WHERE job_id = $1::uuid
          AND subgraph_id = ANY($2::text[])
    """
    result = await db.execute(sql_subgraphs, job_id, subgraph_ids)
    deleted["subgraphs"] = _parse_delete_count(result)
    logger.info(
        f"[排除零件清理] 删除 subgraphs: {deleted['subgraphs']} 条"
    )

    return deleted


async def _update_job_subgraph_count(job_id: str, remaining_count: int):
    """更新 jobs.total_subgraphs 字段。"""
    sql = """
        UPDATE jobs
        SET total_subgraphs = $2, updated_at = NOW()
        WHERE job_id = $1::uuid
    """
    await db.execute(sql, job_id, remaining_count)
    logger.info(
        f"[排除零件清理] 更新 jobs.total_subgraphs = {remaining_count}"
    )


# ============================================================================
# 工具函数
# ============================================================================

def _parse_delete_count(result: str) -> int:
    """从 asyncpg 的 DELETE 返回值中提取删除行数。

    asyncpg execute 返回类似 'DELETE 5' 的字符串。
    """
    try:
        parts = str(result).strip().split()
        if len(parts) >= 2:
            return int(parts[-1])
    except (ValueError, IndexError):
        pass
    return 0


def _build_result(
    job_id: str,
    total: int,
    excluded: int,
    excluded_ids: List[str],
    deleted_counts: Dict[str, int]
) -> Dict[str, Any]:
    """构建统一的返回结构。"""
    return {
        "status": "ok",
        "job_id": job_id,
        "total_subgraphs": total,
        "excluded_count": excluded,
        "remaining_count": total - excluded,
        "excluded_subgraph_ids": excluded_ids,
        "deleted_tables": deleted_counts
    }
