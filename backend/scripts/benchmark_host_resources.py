"""Sample whole-host and process-tree resources during a deployment scenario.

Run this on the target Linux host while separately driving idle connections,
one/two Agent tasks, image search, or the post-task idle window. The output is
append-friendly JSON and includes Chromium descendants in the process tree.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def _status(pid: int) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            name, separator, raw = line.partition(":")
            if separator and name in {"VmRSS", "VmSwap"}:
                values[name] = int(raw.strip().split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return values


def _process_tree(root_pid: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="utf-8").split()
            pid, parent = int(fields[0]), int(fields[3])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent, []).append(pid)
    result: list[int] = []
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in result:
            continue
        result.append(pid)
        pending.extend(children.get(pid, ()))
    return result


def _mem_available_kib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except (OSError, IndexError, ValueError):
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True, help="Uvicorn worker PID")
    parser.add_argument("--label", required=True)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "posix" or not Path("/proc").is_dir():
        raise SystemExit("benchmark_host_resources.py must run on the Linux target host")

    samples = []
    deadline = time.monotonic() + max(0.1, args.duration)
    while time.monotonic() < deadline:
        pids = _process_tree(args.pid)
        statuses = [_status(pid) for pid in pids]
        samples.append(
            {
                "elapsed_seconds": round(max(0.0, args.duration - (deadline - time.monotonic())), 3),
                "process_count": len(pids),
                "process_tree_rss_kib": sum(item.get("VmRSS", 0) for item in statuses),
                "process_tree_swap_kib": sum(item.get("VmSwap", 0) for item in statuses),
                "host_mem_available_kib": _mem_available_kib(),
            }
        )
        time.sleep(max(0.05, args.interval))

    report = {
        "label": args.label,
        "root_pid": args.pid,
        "duration_seconds": args.duration,
        "interval_seconds": args.interval,
        "peak_process_tree_rss_kib": max(item["process_tree_rss_kib"] for item in samples),
        "peak_process_tree_swap_kib": max(item["process_tree_swap_kib"] for item in samples),
        "minimum_host_mem_available_kib": min(
            item["host_mem_available_kib"]
            for item in samples
            if item["host_mem_available_kib"] is not None
        ),
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(report, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
