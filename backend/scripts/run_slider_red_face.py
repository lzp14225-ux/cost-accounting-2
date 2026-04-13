# -*- coding: utf-8 -*-
"""
滑块红色面提取调度脚本（在 conda NX 环境里运行）

流程：
  1. 查询数据库，找出有 xt_file_url 且 features.wire_cut_details 含"滑"的子图
  2. 从 MinIO 下载 .x_t 文件到临时目录
  3. 生成 input.json，调用 run_journal.exe 无界面运行 run_slider_red_face_in_nx.py
  4. 读取 output.json，将红色面数据写回数据库

运行方式：
  conda activate NX
  python run_slider_red_face.py
  python run_slider_red_face.py --job-id <job_id>   # 只处理指定 job
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import subprocess
import argparse
from pathlib import Path

# ── 日志 ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            Path(__file__).parent / 'slider_red_face.log',
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

DB_CONFIG = {
    'host':     os.getenv('DB_HOST',     '192.168.3.61'),
    'port':     int(os.getenv('DB_PORT', '5432')),
    'dbname':   os.getenv('DB_NAME',     'mold_cost_db'),
    'user':     os.getenv('DB_USER',     'root'),
    'password': os.getenv('DB_PASSWORD', 'yunzai123'),
}

MINIO_ENDPOINT   = os.getenv('MINIO_ENDPOINT',   '192.168.1.157:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY',  'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY',  'minioadmin')
MINIO_BUCKET     = os.getenv('MINIO_BUCKET',      'files')
MINIO_USE_HTTPS  = os.getenv('MINIO_USE_HTTPS',   'false').lower() == 'true'

NX_BIN_DIR   = Path(os.getenv('NX_BIN_DIR', r'D:\Program Files\Siemens\NX2312\NXBIN'))
RUN_JOURNAL  = NX_BIN_DIR / 'run_journal.exe'
NX_SCRIPT    = Path(__file__).parent / 'run_slider_red_face_in_nx.py'


# ── 数据库 ────────────────────────────────────────────────────────

def get_conn():
    import psycopg2
    return psycopg2.connect(**DB_CONFIG)


def query_slider_subgraphs(job_id=None):
    """
    查询有 xt_file_url 且 features.wire_cut_details 含"滑"的子图。
    返回 list of dict: subgraph_id, job_id, xt_file_url, part_code
    """
    conn = get_conn()
    cur  = conn.cursor()
    try:
        if job_id:
            cur.execute("""
                SELECT s.subgraph_id, s.job_id, s.xt_file_url, s.part_code,
                       f.metadata
                FROM subgraphs s
                JOIN features f ON f.subgraph_id = s.subgraph_id
                                AND f.job_id      = s.job_id
                WHERE s.job_id = %s
                  AND s.xt_file_url IS NOT NULL
                ORDER BY s.part_code
            """, (job_id,))
        else:
            cur.execute("""
                SELECT s.subgraph_id, s.job_id, s.xt_file_url, s.part_code,
                       f.metadata
                FROM subgraphs s
                JOIN features f ON f.subgraph_id = s.subgraph_id
                                AND f.job_id      = s.job_id
                WHERE s.xt_file_url IS NOT NULL
                ORDER BY s.job_id, s.part_code
            """)

        rows = cur.fetchall()
        result = []
        for subgraph_id, jid, xt_url, part_code, metadata in rows:
            wcd = (metadata or {}).get('wire_cut_details', [])
            if any('滑' in d.get('instruction', '') for d in wcd):
                result.append({
                    'subgraph_id': subgraph_id,
                    'job_id':      jid,
                    'xt_file_url': xt_url,
                    'part_code':   part_code,
                })
        logger.info(f"查询到 {len(result)} 个含滑块工艺的子图（共扫描 {len(rows)} 条）")
        return result
    finally:
        cur.close()
        conn.close()


def write_results_to_db(results):
    """
    将 NX 提取结果写入 features.metadata.wire_cut_details。
    instruction 含"滑"的条目 → code='滑块', view='front_view',
    total_length=总面积, area_num=面数量, matched_count=面数量
    """
    import psycopg2.extras

    conn = get_conn()
    cur  = conn.cursor()
    success = skip = fail = 0

    try:
        for item in results:
            subgraph_id    = item['subgraph_id']
            job_id         = item['job_id']
            red_face_count = item['red_face_count']
            total_area     = item['total_area']
            error          = item.get('error')

            if error or red_face_count == 0:
                logger.info(f"跳过 {subgraph_id}: {error or 'no_red_face'}")
                skip += 1
                continue

            cur.execute(
                "SELECT metadata FROM features "
                "WHERE subgraph_id = %s AND job_id = %s",
                (subgraph_id, job_id)
            )
            row = cur.fetchone()
            if not row:
                logger.warning(f"未找到 features 记录: {subgraph_id}")
                fail += 1
                continue

            metadata = row[0] or {}
            wcd = metadata.get('wire_cut_details', [])
            updated = False
            for d in wcd:
                if '滑' in d.get('instruction', ''):
                    d['code']          = '滑块'
                    d['view']          = 'front_view'
                    d['total_length']  = total_area
                    d['area_num']      = red_face_count
                    d['matched_count'] = red_face_count
                    updated = True

            if not updated:
                logger.info(f"未找到含'滑'的 instruction，跳过: {subgraph_id}")
                skip += 1
                continue

            metadata['wire_cut_details'] = wcd
            cur.execute(
                "UPDATE features SET metadata = %s "
                "WHERE subgraph_id = %s AND job_id = %s",
                (psycopg2.extras.Json(metadata), subgraph_id, job_id)
            )
            logger.info(
                f"✅ {subgraph_id} | 红色面={red_face_count}个 | 总面积={total_area}mm²"
            )
            success += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"写入数据库失败: {e}")
        raise
    finally:
        cur.close()
        conn.close()

    return success, skip, fail


# ── MinIO ─────────────────────────────────────────────────────────

def get_minio():
    from minio import Minio
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_HTTPS
    )


def download_xt(minio, xt_minio_path, local_path):
    try:
        minio.fget_object(MINIO_BUCKET, xt_minio_path, local_path)
        return True
    except Exception as e:
        logger.error(f"下载失败 {xt_minio_path}: {e}")
        return False


# ── NX 调用 ───────────────────────────────────────────────────────

def run_nx_extract(input_json_path, output_json_path):
    """
    调用 run_journal.exe 无界面运行 NX 脚本提取红色面。
    返回 True/False。
    """
    if not RUN_JOURNAL.exists():
        logger.error(f"run_journal.exe 不存在: {RUN_JOURNAL}")
        return False

    cmd = [
        str(RUN_JOURNAL),
        str(NX_SCRIPT),
        '-args',
        str(input_json_path),
        str(output_json_path),
    ]

    # 设置 NX 所需环境变量
    env = os.environ.copy()
    env['UGII_BASE_DIR']  = str(NX_BIN_DIR.parent / 'UGII')
    env['UGII_ROOT_DIR']  = str(NX_BIN_DIR.parent / 'UGII')
    env['PATH']           = str(NX_BIN_DIR) + os.pathsep + env.get('PATH', '')

    logger.info(f"调用 NX: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,          # 5 分钟超时
            cwd=str(NX_BIN_DIR),
        )
        if proc.stdout:
            for line in proc.stdout.splitlines():
                logger.info(f"  [NX stdout] {line}")
        if proc.stderr:
            for line in proc.stderr.splitlines():
                logger.warning(f"  [NX stderr] {line}")

        if proc.returncode != 0:
            logger.error(f"run_journal.exe 退出码: {proc.returncode}")
            return False

        return True

    except subprocess.TimeoutExpired:
        logger.error("run_journal.exe 超时（>300s）")
        return False
    except Exception as e:
        logger.error(f"调用 run_journal.exe 失败: {e}")
        return False


# ── 主流程 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='滑块红色面提取')
    parser.add_argument('--job-id', help='只处理指定 job_id')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("开始滑块红色面提取")
    logger.info("=" * 60)

    # 1. 查询需要处理的子图
    subgraphs = query_slider_subgraphs(args.job_id)
    if not subgraphs:
        logger.info("没有需要处理的子图，退出")
        return

    minio = get_minio()
    tmp_dir = tempfile.mkdtemp(prefix='slider_xt_')
    logger.info(f"临时目录: {tmp_dir}")

    try:
        # 2. 下载 .x_t 文件，构建 input.json
        tasks = []
        for sg in subgraphs:
            xt_url   = sg['xt_file_url']
            filename = os.path.basename(xt_url)
            local    = os.path.join(tmp_dir, f"{sg['subgraph_id']}_{filename}")

            logger.info(f"下载: {xt_url} -> {local}")
            if download_xt(minio, xt_url, local):
                tasks.append({
                    'subgraph_id':  sg['subgraph_id'],
                    'job_id':       sg['job_id'],
                    'xt_local_path': local,
                })
            else:
                logger.warning(f"下载失败，跳过: {sg['part_code']}")

        if not tasks:
            logger.warning("所有文件下载失败，退出")
            return

        input_json  = os.path.join(tmp_dir, 'nx_input.json')
        output_json = os.path.join(tmp_dir, 'nx_output.json')

        with open(input_json, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

        logger.info(f"共 {len(tasks)} 个任务，写入 {input_json}")

        # 3. 调用 NX 提取红色面
        ok = run_nx_extract(input_json, output_json)
        if not ok:
            logger.error("NX 提取失败，退出")
            return

        if not os.path.exists(output_json):
            logger.error(f"output.json 不存在: {output_json}")
            return

        with open(output_json, 'r', encoding='utf-8') as f:
            nx_results = json.load(f)

        logger.info(f"NX 返回 {len(nx_results)} 条结果")

        # 4. 写入数据库
        success, skip, fail = write_results_to_db(nx_results)

        logger.info("=" * 60)
        logger.info(f"完成: 成功={success}, 跳过={skip}, 失败={fail}")
        logger.info("=" * 60)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info(f"临时目录已清理: {tmp_dir}")


if __name__ == '__main__':
    main()
