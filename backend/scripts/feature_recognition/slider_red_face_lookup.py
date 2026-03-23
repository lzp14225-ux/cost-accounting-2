# -*- coding: utf-8 -*-
"""
滑块红色面查表模块（MinIO 版）

功能：
  在特征识别保存数据库前，用 part_code 查询存放在 MinIO 上的
  feature_database.json，将红色面数据补充到 wire_cut_details 中
  instruction 含"滑"的条目，避免每次都需要启动 NX 提取。

MinIO 路径规则：
  slider/feature_database.json   （默认，可通过 .env SLIDER_FEATURE_DB_MINIO_PATH 覆盖）

JSON 格式（两种均支持）：
  格式1 - build_feature_database.py 生成（推荐）：
    { "DIE-06": { "wire_cut_details": [{...}] }, ... }

  格式2 - 旧版 slider_feature_database.json：
    { "sliders": { "DIE-06": { "feature_face_count": 6, "feature_faces": [...] } } }

查找规则（大小写不敏感，支持前缀匹配）：
  part_code "DIE-06" 可匹配 "DIE-06", "die-06", "DIE-06A" 等

上传方式（手动执行一次）：
  python slider_recognition/upload_feature_db.py <feature_database.json路径>
"""

import os
import json
import logging
import tempfile
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# MinIO 中 feature_database.json 的默认路径
_DEFAULT_MINIO_PATH = os.getenv('SLIDER_FEATURE_DB_MINIO_PATH', 'slider/feature_database.json')

# 模块级内存缓存：{ minio_path: normalized_dict }
# 进程内只下载一次
_DB_CACHE: Dict[str, Dict[str, Any]] = {}


# ──────────────────────────────────────────────────────────────
# 内部：解析 JSON → 统一格式
# ──────────────────────────────────────────────────────────────

def _parse_raw(raw: dict) -> Dict[str, Any]:
    """
    将两种格式的原始 JSON 统一转换为：
      { part_code_lower: { "wire_cut_details": [...] } }
    """
    normalized: Dict[str, Any] = {}

    # 格式1：顶层 key 就是零件编号，value 含 wire_cut_details
    first_val = next(iter(raw.values()), None) if raw else None
    if isinstance(first_val, dict) and 'wire_cut_details' in first_val:
        for code, data in raw.items():
            normalized[code.lower()] = data
        return normalized

    # 格式2：{ "sliders": { "DIE-06": { "feature_face_count": N, "feature_faces": [...] } } }
    for code, data in raw.get('sliders', {}).items():
        face_count = data.get('feature_face_count', 0)
        faces = data.get('feature_faces', [])
        total_area = round(sum(f.get('area', 0.0) for f in faces), 3)
        single = round(total_area / face_count, 3) if face_count else 0.0
        normalized[code.lower()] = {
            'wire_cut_details': [{
                'code':              '滑块',
                'cone':              'f',
                'view':              'front_view',
                'area_num':          face_count,
                'instruction':       f'{face_count} -红色面',
                'slider_angle':      0,
                'total_length':      total_area,
                'is_additional':     False,
                'matched_count':     face_count,
                'single_length':     single,
                'expected_count':    face_count,
                'matched_line_ids':  [],
                'overlapping_length': 0.0,
            }]
        }

    return normalized


# ──────────────────────────────────────────────────────────────
# 内部：从 MinIO 加载数据库（带内存缓存）
# ──────────────────────────────────────────────────────────────

def _load_from_minio(minio_path: str, minio_client) -> Dict[str, Any]:
    """
    从 MinIO 下载 feature_database.json 并解析。
    结果缓存在内存中，进程内只下载一次。
    """
    if minio_path in _DB_CACHE:
        return _DB_CACHE[minio_path]

    # 下载到临时文件
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        ok = minio_client.get_file(minio_path, tmp_path)
        if not ok:
            logger.warning(f"MinIO 下载 feature_database 失败: {minio_path}")
            return {}

        with open(tmp_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        normalized = _parse_raw(raw)
        logger.info(f"加载 feature_database from MinIO: {len(normalized)} 条 | {minio_path}")
        _DB_CACHE[minio_path] = normalized
        return normalized

    except Exception as e:
        logger.warning(f"加载 feature_database 失败: {minio_path} - {e}")
        return {}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# 内部：查找条目
# ──────────────────────────────────────────────────────────────

def _find_entry(db: Dict[str, Any], part_code: str) -> Optional[Dict[str, Any]]:
    """大小写不敏感精确匹配，不做前缀匹配避免误命中"""
    key = part_code.lower().strip()
    return db.get(key)


# ──────────────────────────────────────────────────────────────
# 公开接口
# ──────────────────────────────────────────────────────────────

def apply_red_face_lookup(
    part_code: str,
    wire_cut_details: List[Dict[str, Any]],
    minio_client=None,
    minio_db_path: Optional[str] = None,
    part_name: str = '',
) -> List[Dict[str, Any]]:
    """
    主入口：若 part_name 中含"滑块"两字，则用 part_code 查 MinIO 上的
    feature_database.json，将红色面数据补充到 wire_cut_details 中。

    规则：
    - 判定条件：part_name 包含"滑块"
    - 满足条件时，对 wire_cut_details 中每个条目：
        - code 强制改为 '滑块'
        - area_num = 红色面数量
        - total_length = 红色面面积和
        - 其余字段（instruction / slider_angle / view / matched_line_ids 等）保留原值
    - 若 wire_cut_details 为空但查到记录，则追加一条
    """
    if not part_code or minio_client is None:
        return wire_cut_details

    # 判定条件：part_name 含"滑块"
    if '滑块' not in (part_name or ''):
        return wire_cut_details

    db_path = minio_db_path or _DEFAULT_MINIO_PATH
    db = _load_from_minio(db_path, minio_client)
    if not db:
        return wire_cut_details

    entry = _find_entry(db, part_code)
    if not entry:
        logger.debug(f"[{part_code}] 未在 feature_database 中找到记录，跳过查表")
        return wire_cut_details

    db_wcd = entry.get('wire_cut_details', [])
    if not db_wcd:
        return wire_cut_details

    db_slider    = db_wcd[0]
    area_num     = db_slider.get('area_num', 0)
    total_length = db_slider.get('total_length', 0.0)
    single_len   = round(total_length / area_num, 3) if area_num else 0.0

    if area_num == 0:
        return wire_cut_details

    logger.info(
        f"[{part_code}] part_name='{part_name}' 含'滑块'，查表补充红色面: "
        f"area_num={area_num}, total_length={total_length}mm²"
    )

    # 合并所有条目为一条 code='滑块' 的记录
    # slider_angle 从所有条目中取最大非零值，都为0则取0
    slider_angle = max((d.get('slider_angle', 0) for d in wire_cut_details), default=0)
    base = dict(wire_cut_details[0]) if wire_cut_details else {}

    base['code']          = '滑块'
    base['instruction']   = '滑块面积'
    base['slider_angle']  = slider_angle
    base['area_num']      = area_num
    base['total_length']  = total_length
    base['single_length'] = single_len
    return [base]


def invalidate_cache(minio_path: Optional[str] = None):
    """清除内存缓存（MinIO 上的 JSON 更新后调用）"""
    if minio_path:
        _DB_CACHE.pop(minio_path, None)
    else:
        _DB_CACHE.clear()
