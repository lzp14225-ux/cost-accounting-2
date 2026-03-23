"""
重放已保存的 NC 响应 JSON，并重新写入 features.nc_time_cost / volume_mm3。

用法示例:
    python scripts/replay_nc_responses.py --job-id <job_id>
    python scripts/replay_nc_responses.py --path logs/nc_responses/<job_id>/subgraphs
    python scripts/replay_nc_responses.py --file logs/nc_responses/<job_id>/subgraphs/U1-01_20260323_042418.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.nc_time_agent import NCTimeAgent


def _resolve_files(job_id: str | None, path: str | None, file_path: str | None) -> list[Path]:
    if file_path:
        target = Path(file_path)
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在: {target}")
        return [target]

    if path:
        target = Path(path)
    elif job_id:
        target = Path("logs") / "nc_responses" / job_id / "subgraphs"
    else:
        raise ValueError("必须提供 --job-id、--path 或 --file 之一")

    if target.is_file():
        return [target]

    if not target.is_dir():
        raise FileNotFoundError(f"目录不存在: {target}")

    return sorted(target.glob("*.json"))


def _extract_volume_data(payload: dict[str, Any]) -> dict[str, Any]:
    volume_mm3 = payload.get("volume_mm3")
    if volume_mm3 is not None:
        return {"volume_mm3": volume_mm3}

    meta_data = payload.get("meta_data")
    if isinstance(meta_data, dict):
        volume_mm3 = meta_data.get("volume_mm3")
        if volume_mm3 is not None:
            return {"volume_mm3": volume_mm3}

    return {}


async def _replay(files: list[Path], dry_run: bool) -> None:
    agent = NCTimeAgent()
    success = 0
    failed = 0

    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
            subgraph_id = payload.get("subgraph_id")
            operations = payload.get("operations", [])

            if not subgraph_id:
                raise ValueError("缺少 subgraph_id")
            if not isinstance(operations, list):
                raise ValueError("operations 不是列表")

            time_data = agent._parse_operations(  # noqa: SLF001
                operations,
                _extract_volume_data(payload),
            )

            if dry_run:
                face_count = len(time_data.get("nc_details", []))
                print(f"[DRY-RUN] {file.name} -> {subgraph_id}, faces={face_count}, volume_mm3={time_data.get('volume_mm3')}")
            else:
                await agent._save_nc_time_data(subgraph_id, time_data)  # noqa: SLF001
                face_count = len(time_data.get("nc_details", []))
                print(f"[OK] {file.name} -> {subgraph_id}, faces={face_count}, volume_mm3={time_data.get('volume_mm3')}")

            success += 1
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {file}: {exc}")

    print(f"完成: success={success}, failed={failed}, total={len(files)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="重放已保存的 NC 响应 JSON")
    parser.add_argument("--job-id", help="任务 ID，会默认读取 logs/nc_responses/<job_id>/subgraphs")
    parser.add_argument("--path", help="JSON 文件目录或单个 JSON 文件路径")
    parser.add_argument("--file", help="单个 JSON 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只解析，不写数据库")
    args = parser.parse_args()

    files = _resolve_files(args.job_id, args.path, args.file)
    if not files:
        raise FileNotFoundError("没有找到可重放的 JSON 文件")

    asyncio.run(_replay(files, args.dry_run))


if __name__ == "__main__":
    main()
