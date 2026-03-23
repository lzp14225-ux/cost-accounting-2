# -*- coding: utf-8 -*-
"""
滑块红色面数据写入模块

功能：
  在 feature_recognition 识别出滑块工艺后，调用本模块：
  1. 接收 subgraph_id / job_id / xt_file_url
  2. 从 MinIO 下载对应的 .x_t 文件
  3. 用 NXOpen 提取红色面的面积和数量
  4. 将结果以 code='滑块' 的 wire_cut_details 条目写入 features.metadata

字段格式参考 build_feature_database.py 生成的结构：
  {
    "code": "滑块",
    "cone": "f",
    "view": "front_view",
    "area_num": <红色面数量>,
    "instruction": "<N> -红色面",
    "slider_angle": 0,
    "total_length": <红色面总面积 mm²>,
    "is_additional": false,
    "matched_count": <红色面数量>,
    "single_length": <平均单面面积 mm²>,
    "expected_count": <红色面数量>,
    "matched_line_ids": [],
    "overlapping_length": 0.0
  }
"""

import os
import json
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# NX 中红色的颜色索引集合（只保留186）
_NX_RED_COLORS = {186}


def _extract_red_face_stats_via_run_journal(xt_file_path: str) -> Optional[Dict[str, Any]]:
    """
    Fallback path that mirrors the standalone scripts flow:
    run run_journal.exe -> run_slider_red_face_in_nx.py -> read output json.
    """
    try:
        feature_dir = Path(__file__).resolve().parent
        backend_scripts_dir = feature_dir.parent
        nx_script = backend_scripts_dir / "run_slider_red_face_in_nx.py"
        nx_bin_dir = Path(os.getenv("NX_BIN_DIR", r"D:\Program Files\Siemens\NX2312\NXBIN"))
        run_journal = nx_bin_dir / "run_journal.exe"
        ugii_dir = nx_bin_dir.parent / "UGII"

        if not nx_script.exists():
            logger.error(f"NX journal script missing: {nx_script}")
            return None
        if not run_journal.exists():
            logger.error(f"run_journal.exe missing: {run_journal}")
            return None

        with tempfile.TemporaryDirectory(prefix="slider_red_face_nx_") as tmp_dir:
            input_json = Path(tmp_dir) / "input.json"
            output_json = Path(tmp_dir) / "output.json"
            input_json.write_text(
                json.dumps(
                    [
                        {
                            "subgraph_id": "fallback",
                            "job_id": "fallback",
                            "xt_local_path": xt_file_path,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cmd = [
                str(run_journal),
                str(nx_script),
                "-args",
                str(input_json),
                str(output_json),
            ]

            env = os.environ.copy()
            env["UGII_BASE_DIR"] = str(ugii_dir)
            env["UGII_ROOT_DIR"] = str(ugii_dir)
            env["PATH"] = str(nx_bin_dir) + os.pathsep + env.get("PATH", "")

            logger.info(f"Fallback to NX journal for red-face extraction: {xt_file_path}")
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(nx_bin_dir),
            )

            if proc.stdout:
                for line in proc.stdout.splitlines():
                    logger.info(f"[NX stdout] {line}")
            if proc.stderr:
                for line in proc.stderr.splitlines():
                    logger.warning(f"[NX stderr] {line}")

            if proc.returncode != 0:
                logger.error(f"run_journal.exe exited with code {proc.returncode}")
                return None
            if not output_json.exists():
                logger.error(f"NX journal output missing: {output_json}")
                return None

            data = json.loads(output_json.read_text(encoding="utf-8"))
            if not data:
                logger.warning(f"NX journal returned empty result for {xt_file_path}")
                return None

            item = data[0]
            if item.get("error"):
                logger.warning(f"NX journal reported error for {xt_file_path}: {item['error']}")
                return None

            red_face_count = int(item.get("red_face_count") or 0)
            total_area = round(float(item.get("total_area") or 0.0), 3)
            single_length = round(total_area / red_face_count, 3) if red_face_count > 0 else 0.0

            return {
                "red_face_count": red_face_count,
                "total_area": total_area,
                "single_length": single_length,
                "face_details": [],
            }
    except Exception as e:
        logger.exception(f"NX journal fallback failed: {e}")
        return None


# ──────────────────────────────────────────────
# NXOpen 红色面提取
# ──────────────────────────────────────────────

def _extract_red_face_stats_nxopen(xt_file_path: str) -> Optional[Dict[str, Any]]:
    """
    使用 NXOpen 提取 .x_t 文件中红色面的统计数据。
    仅在 NX 环境中可用。

    Returns:
        {
            "red_face_count": int,
            "total_area": float,    # 红色面总面积 mm²
            "single_length": float, # 平均单面面积 mm²
            "face_details": [{"area": float, "perimeter": float, "color": int}, ...]
        }
        失败时返回 None
    """
    try:
        import NXOpen

        session = NXOpen.Session.GetSession()

        open_result = session.Parts.Open(xt_file_path)
        work_part = open_result[0] if isinstance(open_result, tuple) else open_result
        session.Parts.SetDisplay(work_part, False, False)
        session.Parts.SetWork(work_part)
        work_part = session.Parts.Work

        measure_mgr = work_part.MeasureManager
        units = work_part.UnitCollection
        area_unit = units.FindObject("SquareMilliMeter")
        length_unit = units.FindObject("MilliMeter")

        face_details: List[Dict] = []
        total_area = 0.0

        for body in work_part.Bodies:
            for face in body.GetFaces():
                try:
                    if face.Color not in _NX_RED_COLORS:
                        continue
                    result = measure_mgr.NewFaceProperties(area_unit, length_unit, 0.01, [face])
                    area = round(result.Area, 3) if hasattr(result, 'Area') else 0.0
                    perimeter = round(result.Perimeter, 3) if hasattr(result, 'Perimeter') else 0.0
                    face_details.append({
                        "area": area,
                        "perimeter": perimeter,
                        "color": face.Color
                    })
                    total_area += area
                except Exception:
                    pass

        # 关闭文件，释放资源
        try:
            session.Parts.CloseAll(NXOpen.BasePart.CloseWholeTree.False_, None)
        except Exception:
            pass

        red_count = len(face_details)
        if red_count == 0:
            logger.info(f"文件中未找到红色面: {xt_file_path}")
            return None

        return {
            "red_face_count": red_count,
            "total_area": round(total_area, 3),
            "single_length": round(total_area / red_count, 3),
            "face_details": face_details
        }

    except ImportError:
        logger.warning("NXOpen 不可用，跳过红色面提取")
        return None
    except Exception as e:
        logger.error(f"NXOpen 提取红色面失败: {e}")
        return None


# ──────────────────────────────────────────────
# 构建 wire_cut_details 条目
# ──────────────────────────────────────────────

def _build_slider_wire_cut_entry(red_face_stats: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据红色面统计数据构建 wire_cut_details 中的滑块条目。
    字段格式与 build_feature_database.py 保持一致。
    """
    red_count = red_face_stats["red_face_count"]
    total_area = red_face_stats["total_area"]
    single_length = red_face_stats["single_length"]

    return {
        "code": "滑块",
        "cone": "f",
        "view": "front_view",
        "area_num": red_count,
        "instruction": f"{red_count} -红色面",
        "slider_angle": 0,
        "total_length": total_area,
        "is_additional": False,
        "matched_count": red_count,
        "single_length": single_length,
        "expected_count": red_count,
        "matched_line_ids": [],
        "overlapping_length": 0.0
    }


# ──────────────────────────────────────────────
# 数据库更新
# ──────────────────────────────────────────────

def _update_features_metadata(
    subgraph_id: str,
    job_id: str,
    slider_entry: Dict[str, Any],
    db_config: Dict[str, Any]
) -> bool:
    """
    将滑块红色面条目写入 features.metadata.wire_cut_details。

    规则：
    - 如果已有 code='滑块' 的条目，则覆盖
    - 否则追加
    """
    try:
        import psycopg2
        from psycopg2.extras import Json

        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        # 读取当前 metadata
        cursor.execute(
            "SELECT metadata FROM features WHERE subgraph_id = %s AND job_id = %s",
            (subgraph_id, job_id)
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(f"未找到 features 记录: subgraph_id={subgraph_id}, job_id={job_id}")
            cursor.close()
            conn.close()
            return False

        metadata = row[0] or {}

        # 更新 wire_cut_details：
        # 找到 instruction 含"滑"的条目，更新 code/view/total_length/area_num，其余字段保留
        # 若不存在则追加新条目
        wire_cut_details = metadata.get("wire_cut_details", [])
        slider_angle = max(
            (float(d.get("slider_angle", 0) or 0) for d in wire_cut_details),
            default=0.0,
        )
        slider_view = next(
            (
                d.get("view")
                for d in wire_cut_details
                if (d.get("code") == "滑块") or ("滑" in (d.get("instruction") or ""))
            ),
            "top_view",
        )

        updated = False
        for d in wire_cut_details:
            if (d.get("code") == "滑块") or ("滑" in (d.get("instruction") or "")):
                d["code"] = "滑块"
                d["total_length"] = slider_entry["total_length"]
                d["area_num"] = slider_entry["area_num"]
                d["matched_count"] = slider_entry["area_num"]
                d["expected_count"] = slider_entry["area_num"]
                d["single_length"] = slider_entry["single_length"]
                # Keep slider angle detected by slider_calculator.
                d["slider_angle"] = float(d.get("slider_angle", slider_angle) or slider_angle)
                if not d.get("view"):
                    d["view"] = slider_view
                updated = True

        if not updated:
            new_entry = dict(slider_entry)
            new_entry["slider_angle"] = slider_angle
            new_entry["view"] = slider_view
            wire_cut_details.append(new_entry)

        # 只保留第一条 code='滑块' 的条目，删除其他所有条目
        slider_entries = [d for d in wire_cut_details if d.get("code") == "滑块"]
        wire_cut_details = [slider_entries[0]] if slider_entries else wire_cut_details
        metadata["wire_cut_details"] = wire_cut_details

        cursor.execute(
            "UPDATE features SET metadata = %s WHERE subgraph_id = %s AND job_id = %s",
            (Json(metadata), subgraph_id, job_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        logger.info(
            f"✅ 滑块红色面写入成功: subgraph_id={subgraph_id}, "
            f"红色面={slider_entry['area_num']}个, 总面积={slider_entry['total_length']}mm²"
        )
        return True

    except Exception as e:
        logger.error(f"写入数据库失败: {e}")
        return False


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def update_slider_red_face_data(
    subgraph_id: str,
    job_id: str,
    xt_file_url: str,
    db_config: Dict[str, Any],
    minio_client=None
) -> bool:
    """
    主入口：下载 .x_t 文件 → 提取红色面 → 写入 features.metadata。

    Args:
        subgraph_id: 子图ID（对应 features 表的 subgraph_id）
        job_id: 任务ID
        xt_file_url: MinIO 中 .x_t 文件路径，或本地绝对路径
        db_config: psycopg2 连接配置 dict
        minio_client: MinIO 客户端实例（可选）

    Returns:
        bool: 是否成功
    """
    logger.info(f"开始处理滑块红色面: subgraph_id={subgraph_id}, xt={xt_file_url}")

    tmp_dir = tempfile.mkdtemp(prefix="slider_xt_")
    xt_local = os.path.join(tmp_dir, os.path.basename(xt_file_url))
    using_tmp = True

    try:
        # 1. 获取 .x_t 文件
        if os.path.isabs(xt_file_url) and os.path.exists(xt_file_url):
            # 本地路径，直接使用，不需要临时目录
            xt_local = xt_file_url
            using_tmp = False
        elif minio_client:
            ok = minio_client.get_file(xt_file_url, xt_local)
            if not ok:
                logger.error(f"下载 .x_t 文件失败: {xt_file_url}")
                return False
        else:
            logger.error(f"无法获取 .x_t 文件（无 minio_client 且非本地路径）: {xt_file_url}")
            return False

        # 2. 提取红色面数据
        red_face_stats = _extract_red_face_stats_nxopen(xt_local)
        if not red_face_stats:
            logger.warning(f"NXOpen direct extraction returned no red-face data, fallback to NX journal: {xt_local}")
            red_face_stats = _extract_red_face_stats_via_run_journal(xt_local)
        if not red_face_stats:
            logger.warning(f"未提取到红色面数据，跳过写入: {xt_local}")
            return False

        # 3. 构建条目
        slider_entry = _build_slider_wire_cut_entry(red_face_stats)

        # 4. 写入数据库
        return _update_features_metadata(subgraph_id, job_id, slider_entry, db_config)

    finally:
        if using_tmp and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass
