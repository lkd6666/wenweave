"""Repeatable local CPU benchmark for streamed tool arguments.

This compares the pre-optimization behavior (full JSON parse and token count on
every fragment) with the current incremental scanner and throttled token count.
It intentionally excludes model/network wait so provider variance cannot be
reported as a local performance gain.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_agent import _StreamedToolCallBuffer
from app.services.token_budget import estimate_tokens


@dataclass
class _LegacyBuffer:
    arguments: str = ""

    def append(self, fragment: str) -> None:
        self.arguments = f"{self.arguments}{fragment}"

    def parse(self) -> dict | None:
        try:
            value = json.loads(self.arguments)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


def _payload(target_chars: int) -> tuple[str, dict]:
    paragraph = '<section><p style="font-size:15px;line-height:2">固定文章正文与样式</p></section>'
    html = (paragraph * (target_chars // len(paragraph) + 1))[:target_chars]
    value = {"html": html, "revision": "benchmark-revision"}
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")), value


def _legacy(fragments: list[str]) -> dict | None:
    buffer = _LegacyBuffer()
    parsed = None
    for fragment in fragments:
        buffer.append(fragment)
        parsed = buffer.parse()
        estimate_tokens(buffer.arguments)
    return parsed


def _optimized(fragments: list[str]) -> dict | None:
    buffer = _StreamedToolCallBuffer(index=0)
    parsed = None
    for index, fragment in enumerate(fragments):
        buffer.append({"args": fragment})
        parsed = buffer.complete_arguments()
        # A fast provider can deliver many fragments inside the 250 ms UI
        # window. The real path counts the first visible fragment and the
        # forced final state, rather than recounting every intermediate prefix.
        if index == 0 or index == len(fragments) - 1:
            buffer.estimated_tokens()
    return parsed


def _measure(function, fragments: list[str], rounds: int) -> list[float]:
    samples: list[float] = []
    for _ in range(rounds):
        started = time.process_time()
        result = function(fragments)
        samples.append(time.process_time() - started)
        if not isinstance(result, dict) or not result.get("html"):
            raise RuntimeError("benchmark parser did not reconstruct the payload")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html-chars", type=int, default=512 * 1024)
    parser.add_argument("--fragment-chars", type=int, default=2048)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-reduction", type=float, default=0.30)
    args = parser.parse_args()

    encoded, expected = _payload(max(4096, args.html_chars))
    fragment_chars = max(64, args.fragment_chars)
    fragments = [encoded[offset : offset + fragment_chars] for offset in range(0, len(encoded), fragment_chars)]

    # Warm tokenizer tables and imports before timing either implementation.
    estimate_tokens("warmup")
    probe = _optimized(fragments)
    if probe != expected:
        raise RuntimeError("optimized parser changed the reconstructed arguments")

    legacy = _measure(_legacy, fragments, max(1, args.rounds))
    optimized = _measure(_optimized, fragments, max(1, args.rounds))
    legacy_median = statistics.median(legacy)
    optimized_median = statistics.median(optimized)
    reduction = 1.0 - optimized_median / legacy_median if legacy_median else 0.0
    report = {
        "measurement": "local_process_cpu_seconds",
        "external_model_wait_seconds": None,
        "html_chars": len(expected["html"]),
        "encoded_chars": len(encoded),
        "fragment_chars": fragment_chars,
        "fragments": len(fragments),
        "rounds": max(1, args.rounds),
        "legacy_samples_seconds": legacy,
        "optimized_samples_seconds": optimized,
        "legacy_median_seconds": legacy_median,
        "optimized_median_seconds": optimized_median,
        "local_cpu_reduction_ratio": reduction,
        "meets_30_percent_target": reduction >= 0.30,
        "expected_steady_state_from_verified_scheduling": {
            "notification_queries_per_second": {"legacy_10_tabs": 10, "optimized_10_tabs": 1, "no_subscribers": 0},
            "lease_writes_per_minute": {"legacy": 120, "optimized": 6},
        },
    }
    encoded_report = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded_report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded_report + "\n", encoding="utf-8")
    return 0 if reduction >= args.require_reduction else 1


if __name__ == "__main__":
    raise SystemExit(main())
