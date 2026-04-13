"""
测试nc识别失败的物料.

Examples:
    cd d:\AI\Pycharm\chengben2\mold_main\backend
  先做只读测试，不写库：
  python scripts/replay_nc_debug_response.py --file logs/nc_agent_debug/response_xxx.json --dry-run  
  例如：
  python scripts/replay_nc_debug_response.py --file logs/nc_agent_debug/response_4d8936ce-ce9a-444d-a508-1f45309450cf_20260410_070231.json --dry-run
  如果输出的 fail_itemcodes 正确，再执行真正写库：
   python scripts/replay_nc_debug_response.py --file logs/nc_agent_debug/response_4d8936ce-ce9a-444d-a508-1f45309450cf_20260410_070231.json
  如果文件名提不出 job_id, 就手动带上:
  python scripts/replay_nc_debug_response.py --file logs/nc_agent_debug/response_4d8936ce-ce9a-444d-a508-1f45309450cf_20260410_070231.json --job-id 8dfe4db6-53bb-4894-a016-87b0fed76e08 --dry-run

    python scripts/replay_nc_debug_response.py --file logs/nc_agent_debug/response_xxx.json
    python scripts/replay_nc_debug_response.py --file logs/nc_agent_debug/response_xxx.json --job-id <job_id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.nc_time_agent import NCTimeAgent


JOB_ID_PATTERN = re.compile(
    r"response_([0-9a-fA-F-]{36})_\d{8}_\d{6}\.json$"
)


def _extract_job_id_from_file(file_path: Path) -> str | None:
    match = JOB_ID_PATTERN.search(file_path.name)
    if not match:
        return None
    return match.group(1)


def _read_payload(file_path: Path) -> dict[str, Any]:
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    return json.loads(file_path.read_text(encoding="utf-8"))


async def _run(file_path: Path, job_id: str | None, dry_run: bool) -> None:
    payload = _read_payload(file_path)
    resolved_job_id = job_id or _extract_job_id_from_file(file_path)
    if not resolved_job_id:
        raise ValueError("Unable to resolve job_id. Pass --job-id explicitly.")

    agent = NCTimeAgent()
    fail_itemcodes = agent._extract_fail_itemcodes(payload)  # noqa: SLF001

    print(f"file={file_path}")
    print(f"job_id={resolved_job_id}")
    print(f"response_code={payload.get('code')}")
    print(f"response_message={payload.get('message')}")
    print(f"fail_itemcodes={fail_itemcodes}")
    print(f"fail_count={len(fail_itemcodes)}")

    if dry_run:
        print("[DRY-RUN] Skip database update.")
        return

    await agent._save_nc_failed_itemcodes(resolved_job_id, fail_itemcodes)  # noqa: SLF001
    print("[OK] Updated jobs.metadata.nc_failed_itemcodes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a raw NC debug response and optionally persist fail_itemcode."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to a raw NC debug response JSON file under logs/nc_agent_debug.",
    )
    parser.add_argument(
        "--job-id",
        help="Override job_id. If omitted, the script extracts it from the file name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and print the extracted result without updating the database.",
    )
    args = parser.parse_args()

    asyncio.run(_run(Path(args.file), args.job_id, args.dry_run))


if __name__ == "__main__":
    main()
