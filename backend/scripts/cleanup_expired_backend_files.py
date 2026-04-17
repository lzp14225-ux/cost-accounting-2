"""后端输出与日志的独立清理脚本。

设计目标：
1. 由 Windows 计划任务直接调用
2. 不再依赖业务流程顺手触发清理
3. 主程序不常驻时也能按计划执行清理
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List


BACKEND_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BACKEND_ROOT / "output"
LOGS_DIR = BACKEND_ROOT / "logs"
PLATE_LINE_STATE_FILE = OUTPUT_DIR / ".plate_line_output_cleanup_state.json"
NC_LOG_STATE_FILE = LOGS_DIR / ".nc_log_cleanup_state.json"
LOG_CLEANUP_STATE_FILE = LOGS_DIR / ".log_cleanup_state.json"
ENV_FILES = (
    BACKEND_ROOT / ".env",
    BACKEND_ROOT / "config" / ".env",
)


@dataclass
class CleanupResult:
    label: str
    deleted_files: int = 0
    deleted_dirs: int = 0
    skipped_files: int = 0
    errors: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "deleted_files": self.deleted_files,
            "deleted_dirs": self.deleted_dirs,
            "skipped_files": self.skipped_files,
            "errors": self.errors,
        }


def _parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]

        values[key] = value

    return values


def _load_env_values() -> Dict[str, str]:
    """按顺序加载可用的 .env 配置，后面的值覆盖前面的值。"""
    values: Dict[str, str] = {}
    for env_file in ENV_FILES:
        values.update(_parse_dotenv(env_file))
    return values


def _get_int_setting(env_values: Dict[str, str], key: str, default: int) -> int:
    """读取整数配置，非法值回退到默认值。"""
    raw_value = os.getenv(key, env_values.get(key, str(default)))
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return max(0, default)


def _utc_timestamp_string(timestamp: float) -> str:
    return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_expired(path: Path, cutoff_ts: float) -> bool:
    return path.stat().st_mtime < cutoff_ts


def _delete_paths(
    label: str,
    paths: Iterable[Path],
    cutoff_ts: float,
    dry_run: bool,
) -> CleanupResult:
    """删除已过期文件；dry-run 模式下只统计，不实际删除。"""
    result = CleanupResult(label=label)
    for path in sorted(set(paths)):
        try:
            if not path.exists():
                continue

            if not _is_expired(path, cutoff_ts):
                result.skipped_files += 1
                continue

            if dry_run:
                result.deleted_files += 1
                continue

            path.unlink()
            result.deleted_files += 1
        except FileNotFoundError:
            continue
        except PermissionError:
            result.errors += 1
        except OSError:
            result.errors += 1
    return result


def _prune_empty_dirs(root_dir: Path, dry_run: bool) -> int:
    """自底向上清理空目录。"""
    if not root_dir.exists():
        return 0

    deleted_dirs = 0
    directories = [path for path in root_dir.rglob("*") if path.is_dir()]
    directories.sort(key=lambda item: len(item.parts), reverse=True)

    for directory in directories:
        try:
            if any(directory.iterdir()):
                continue
            if dry_run:
                deleted_dirs += 1
                continue
            directory.rmdir()
            deleted_dirs += 1
        except OSError:
            continue

    return deleted_dirs


def _collect_files(root_dir: Path, patterns: Iterable[str]) -> List[Path]:
    """按 glob 模式收集文件。"""
    files: List[Path] = []
    if not root_dir.exists():
        return files

    for pattern in patterns:
        files.extend(path for path in root_dir.rglob(pattern) if path.is_file())
    return files


def _collect_root_log_files(logs_dir: Path) -> List[Path]:
    """收集 logs 根目录下需要参与保留期清理的日志文件和归档。"""
    if not logs_dir.exists():
        return []

    files: List[Path] = []
    for path in logs_dir.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.startswith(".") and name.endswith("_cleanup_state.json"):
            continue
        if name.endswith(".log") or ".log." in name:
            files.append(path)
            continue
        if name.endswith(".json") or ".json." in name:
            files.append(path)
    return files


def _write_state_file(
    path: Path,
    retention_days: int,
    result: CleanupResult,
    dry_run: bool,
    now_ts: float,
) -> None:
    """写入本次清理状态，供排查与审计使用。"""
    if dry_run:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_cleanup_ts": now_ts,
        "last_cleanup_at": _utc_timestamp_string(now_ts),
        "retention_days": retention_days,
        "mode": "dry_run" if dry_run else "scheduled_cleanup",
        **result.to_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_plate_line_outputs(retention_days: int, dry_run: bool, now_ts: float) -> CleanupResult:
    """清理 output 目录下的板料线补线 DXF 输出。"""
    if retention_days <= 0:
        return CleanupResult(label="plate_line_output")

    cutoff_ts = now_ts - (retention_days * 24 * 60 * 60)
    result = _delete_paths(
        label="plate_line_output",
        paths=_collect_files(OUTPUT_DIR, ["*_plate_line.dxf"]),
        cutoff_ts=cutoff_ts,
        dry_run=dry_run,
    )
    result.deleted_dirs = _prune_empty_dirs(OUTPUT_DIR, dry_run=dry_run)
    _write_state_file(PLATE_LINE_STATE_FILE, retention_days, result, dry_run, now_ts)
    return result


def cleanup_nc_json_logs(retention_days: int, dry_run: bool, now_ts: float) -> CleanupResult:
    """清理 NC 调试与返回结果目录下的 JSON 文件。"""
    if retention_days <= 0:
        return CleanupResult(label="nc_json_logs")

    cutoff_ts = now_ts - (retention_days * 24 * 60 * 60)
    paths = []
    paths.extend(_collect_files(LOGS_DIR / "nc_agent_debug", ["*.json"]))
    paths.extend(_collect_files(LOGS_DIR / "nc_responses", ["*.json"]))
    result = _delete_paths(
        label="nc_json_logs",
        paths=paths,
        cutoff_ts=cutoff_ts,
        dry_run=dry_run,
    )
    result.deleted_dirs = _prune_empty_dirs(LOGS_DIR / "nc_agent_debug", dry_run=dry_run)
    result.deleted_dirs += _prune_empty_dirs(LOGS_DIR / "nc_responses", dry_run=dry_run)
    _write_state_file(NC_LOG_STATE_FILE, retention_days, result, dry_run, now_ts)
    return result


def cleanup_nc_excel_logs(retention_days: int, dry_run: bool, now_ts: float) -> CleanupResult:
    """清理 logs/ncexcel 目录下下载的 NC Excel 文件。"""
    if retention_days <= 0:
        return CleanupResult(label="nc_excel_logs")

    cutoff_ts = now_ts - (retention_days * 24 * 60 * 60)
    result = _delete_paths(
        label="nc_excel_logs",
        paths=_collect_files(LOGS_DIR / "ncexcel", ["*.xlsx"]),
        cutoff_ts=cutoff_ts,
        dry_run=dry_run,
    )
    result.deleted_dirs = _prune_empty_dirs(LOGS_DIR / "ncexcel", dry_run=dry_run)
    return result


def cleanup_root_logs(retention_days: int, dry_run: bool, now_ts: float) -> CleanupResult:
    """清理 logs 根目录下的 .log / .json 及其轮转归档。"""
    if retention_days <= 0:
        return CleanupResult(label="root_logs")

    cutoff_ts = now_ts - (retention_days * 24 * 60 * 60)
    result = _delete_paths(
        label="root_logs",
        paths=_collect_root_log_files(LOGS_DIR),
        cutoff_ts=cutoff_ts,
        dry_run=dry_run,
    )
    _write_state_file(LOG_CLEANUP_STATE_FILE, retention_days, result, dry_run, now_ts)
    return result


def build_summary(results: Iterable[CleanupResult]) -> Dict[str, Dict[str, int]]:
    """把每类清理结果整理成统一输出结构。"""
    return {result.label: result.to_dict() for result in results}


def main() -> int:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="清理后端中过期的输出文件和日志文件。")
    parser.add_argument("--dry-run", action="store_true", help="只显示将删除哪些文件，不执行实际删除。")
    args = parser.parse_args()

    env_values = _load_env_values()
    now_ts = time.time()

    plate_line_retention_days = _get_int_setting(env_values, "PLATE_LINE_OUTPUT_RETENTION_DAYS", 7)
    nc_log_retention_days = _get_int_setting(env_values, "NC_LOG_RETENTION_DAYS", 7)
    nc_excel_retention_days = _get_int_setting(env_values, "NC_EXCEL_RETENTION_DAYS", 7)
    root_log_retention_days = _get_int_setting(env_values, "LOG_RETENTION_DAYS", 30)

    results = [
        cleanup_plate_line_outputs(plate_line_retention_days, args.dry_run, now_ts),
        cleanup_nc_json_logs(nc_log_retention_days, args.dry_run, now_ts),
        cleanup_nc_excel_logs(nc_excel_retention_days, args.dry_run, now_ts),
        cleanup_root_logs(root_log_retention_days, args.dry_run, now_ts),
    ]

    # 输出结构化结果，便于手动查看或被计划任务日志收集。
    summary = {
        "backend_root": str(BACKEND_ROOT),
        "dry_run": args.dry_run,
        "retention_days": {
            "plate_line_output": plate_line_retention_days,
            "nc_json_logs": nc_log_retention_days,
            "nc_excel_logs": nc_excel_retention_days,
            "root_logs": root_log_retention_days,
        },
        "results": build_summary(results),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0 if sum(item.errors for item in results) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
