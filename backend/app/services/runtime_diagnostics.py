"""Low-overhead process diagnostics used to explain memory-related failures."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessMemory:
    rss_kib: int | None
    swap_kib: int | None


def read_process_memory() -> ProcessMemory:
    """Read Linux RSS and swap counters without adding a runtime dependency."""
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition(":")
            if separator and name in {"VmRSS", "VmSwap"}:
                values[name] = int(value.strip().split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return ProcessMemory(values.get("VmRSS"), values.get("VmSwap"))


def log_process_memory(
    logger: logging.Logger,
    *,
    stage: str,
    worker_id: str,
    run_id: str | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> ProcessMemory:
    """Emit one structured, grep-friendly memory sample at a lifecycle boundary."""
    memory = read_process_memory()
    extras = "".join(
        f" {key}={str(value).replace(' ', '_')}"
        for key, value in fields.items()
        if value is not None
    )
    logger.log(
        level,
        "worker_memory stage=%s pid=%s worker_id=%s run_id=%s rss_kib=%s swap_kib=%s%s",
        stage,
        os.getpid(),
        worker_id,
        run_id or "-",
        memory.rss_kib if memory.rss_kib is not None else "-",
        memory.swap_kib if memory.swap_kib is not None else "-",
        extras,
    )
    return memory
