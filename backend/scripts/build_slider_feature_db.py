# -*- coding: utf-8 -*-
"""
滑块特征库一键构建脚本

功能：
  1. 调用 run_journal.exe 无界面运行 NX 识别脚本，生成 特征面识别报告_增强版.csv
  2. 读取 CSV → 生成 feature_database.json
  3. 上传 feature_database.json 到 MinIO

用法：
  python build_slider_feature_db.py <拆分文件夹路径>

示例：
  python build_slider_feature_db.py "slider_recognition/P3-2026.1.31_split"
  python build_slider_feature_db.py "D:\\my_project\\cadagent\\scripts\\slider_recognition\\P3-2026.1.31_split"
"""

import os
import sys
import csv
import json
import glob
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# ── 加载配置 ──────────────────────────────────────────────────
_root = Path(__file__).parent
load_dotenv(_root / '.env')

NX_BIN_DIR  = Path(os.getenv('NX_BIN_DIR', r'D:\Program Files\Siemens\NX2312\NXBIN'))
RUN_JOURNAL = NX_BIN_DIR / 'run_journal.exe'
NX_SCRIPT   = _root / 'feature_recognition' / 'recognize_by_features_enhanced.py'
MINIO_PATH  = os.getenv('SLIDER_FEATURE_DB_MINIO_PATH', 'slider/feature_database.json')


# ── 步骤1：NX 识别 → CSV ───────────────────────────────────────

def step1_nx_recognize(split_folder: str) -> str:
    """
    调用 run_journal.exe 无界面运行识别脚本。
    返回生成的 CSV 路径，失败抛出异常。
    """
    if not RUN_JOURNAL.exists():
        raise FileNotFoundError(f"run_journal.exe 不存在: {RUN_JOURNAL}")
    if not NX_SCRIPT.exists():
        raise FileNotFoundError(f"NX 识别脚本不存在: {NX_SCRIPT}")

    cmd = [
        str(RUN_JOURNAL),
        str(NX_SCRIPT),
        '-args',
        split_folder,
    ]

    env = os.environ.copy()
    env['UGII_BASE_DIR'] = str(NX_BIN_DIR.parent / 'UGII')
    env['UGII_ROOT_DIR'] = str(NX_BIN_DIR.parent / 'UGII')
    env['PATH'] = str(NX_BIN_DIR) + os.pathsep + env.get('PATH', '')

    print(f"[步骤1] 调用 NX 识别: {split_folder}")
    print(f"        命令: {' '.join(cmd)}")

    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=7200,         # 2 小时超时（1000+ 文件时可能较慢）
        cwd=str(NX_BIN_DIR),
    )

    for line in proc.stdout.splitlines():
        print(f"  [NX] {line}")
    for line in proc.stderr.splitlines():
        print(f"  [NX stderr] {line}")

    if proc.returncode != 0:
        raise RuntimeError(f"run_journal.exe 退出码: {proc.returncode}")

    # 找最新生成的 CSV
    pattern = os.path.join(split_folder, "特征面识别报告_增强版*.csv")
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not files:
        raise FileNotFoundError(f"未找到识别报告 CSV: {split_folder}")

    csv_path = files[-1]
    print(f"[步骤1] ✅ CSV 生成: {csv_path}")
    return csv_path


# ── 步骤2：CSV → feature_database.json ────────────────────────

def step2_build_json(csv_path: str) -> str:
    """
    读取 CSV，生成 feature_database.json。
    返回 JSON 文件路径。
    """
    print(f"[步骤2] 读取 CSV: {csv_path}")
    database = {}

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            part_name = row.get('零件名', '').strip()
            if not part_name:
                continue
            # 跳过汇总统计行
            if any('\u4e00' <= c <= '\u9fff' for c in part_name):
                continue
            red_count_str = row.get('红色面数量', '0').strip()
            # 仅读取红色面总面积（支持 mm2 或 mm²）
            area_str = row.get('红色面总面积(mm2)', row.get('红色面总面积(mm²)', '0')).strip()
            red_count = int(red_count_str) if red_count_str.isdigit() else 0
            if red_count == 0:
                continue
            try:
                total_area = float(area_str)
            except ValueError:
                total_area = 0.0
            slider_result = row.get('识别结果', '').strip()
            code = '滑块' if slider_result not in ('', '未识别') else 'none'
            database[part_name] = {
                "wire_cut_details": [{
                    "code":              code,
                    "cone":              "f",
                    "view":              "front_view",
                    "area_num":          red_count,
                    "instruction":       f"{red_count} -红色面",
                    "slider_angle":      0,
                    "total_length":      round(total_area, 3),
                    "is_additional":     False,
                    "matched_count":     red_count,
                    "single_length":     round(total_area / red_count, 3) if red_count else 0.0,
                    "expected_count":    red_count,
                    "matched_line_ids":  [],
                    "overlapping_length": 0.0,
                }]
            }

    if not database:
        raise ValueError("CSV 中没有有效的红色面数据（所有零件 red_count=0）")

    sliders_dir = os.path.join(os.path.dirname(csv_path), '_sliders')
    os.makedirs(sliders_dir, exist_ok=True)
    json_path = os.path.join(sliders_dir, 'feature_database.json')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(database, f, ensure_ascii=False, indent=2)

    print(f"[步骤2] ✅ JSON 生成: {json_path}（{len(database)} 条记录）")
    return json_path


# ── 步骤3：上传 MinIO ──────────────────────────────────────────

def step3_upload_minio(json_path: str):
    """上传 feature_database.json 到 MinIO，并清除内存缓存。"""
    sys.path.insert(0, str(_root))
    from minio_client import minio_client as mc

    print(f"[步骤3] 上传到 MinIO: {MINIO_PATH}")
    ok = mc.upload_file(json_path, MINIO_PATH)
    if not ok:
        raise RuntimeError("MinIO 上传失败")

    # 清除查表模块的内存缓存
    try:
        from feature_recognition.slider_red_face_lookup import invalidate_cache
        invalidate_cache(MINIO_PATH)
        print(f"[步骤3] 内存缓存已清除")
    except Exception:
        pass

    print(f"[步骤3] ✅ 上传成功: MinIO -> {MINIO_PATH}")


# ── 主流程 ─────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    split_folder = os.path.abspath(sys.argv[1])
    if not os.path.isdir(split_folder):
        print(f"[!] 文件夹不存在: {split_folder}")
        sys.exit(1)

    print("=" * 60)
    print("滑块特征库一键构建")
    print("=" * 60)
    print(f"拆分文件夹: {split_folder}")
    print(f"MinIO 目标: {MINIO_PATH}")
    print("=" * 60)

    try:
        csv_path  = step1_nx_recognize(split_folder)
        json_path = step2_build_json(csv_path)
        step3_upload_minio(json_path)

        print()
        print("=" * 60)
        print("✅ 全部完成！特征识别流程将自动查表补充红色面数据。")
        print("=" * 60)

    except subprocess.TimeoutExpired:
        print("[!] NX 识别超时（>600s），请检查文件数量或手动运行")
        sys.exit(1)
    except Exception as e:
        print(f"[!] 失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
