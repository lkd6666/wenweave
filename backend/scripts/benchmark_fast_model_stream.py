"""Measure local CPU for fast text and cumulative tool-argument streams.

The legacy functions reproduce the removed per-token response merges, timeline
concatenation, event serialization, and full-prefix progress markers. The
optimized functions exercise the production accumulators directly. Provider
network wait is deliberately excluded.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from langchain_core.messages import AIMessageChunk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_agent import (  # noqa: E402
    _AIMessageChunkAccumulator,
    _ModelDeltaBatcher,
    _StreamedToolCallBuffer,
    _ToolProgressTracker,
)


def _measure(function, rounds: int) -> list[float]:
    samples: list[float] = []
    for _ in range(max(1, rounds)):
        started = time.process_time()
        function()
        samples.append(time.process_time() - started)
    return samples


def _scenario_report(legacy: list[float], optimized: list[float]) -> dict[str, object]:
    legacy_median = statistics.median(legacy)
    optimized_median = statistics.median(optimized)
    reduction = 1.0 - optimized_median / legacy_median if legacy_median else 0.0
    return {
        "legacy_samples_seconds": legacy,
        "optimized_samples_seconds": optimized,
        "legacy_median_seconds": legacy_median,
        "optimized_median_seconds": optimized_median,
        "local_cpu_reduction_ratio": reduction,
    }


def _tool_payload(characters: int) -> str:
    return json.dumps(
        {"html": "<section><p>" + ("正文" * characters) + "</p></section>", "revision": "benchmark"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _legacy_cumulative_tool_stream(encoded: str, fragment_chars: int) -> None:
    arguments = ""
    timeout_markers: set[str] = set()
    accounting_markers: set[str] = set()
    for end in range(fragment_chars, len(encoded) + fragment_chars, fragment_chars):
        raw = encoded[: min(end, len(encoded))]
        call = {"index": 0, "name": "replace_document" if not arguments else "", "args": raw}
        # The removed path performed this full-prefix serialization in both
        # timeout supervision and accounting telemetry.
        marker = json.dumps(call, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        timeout_markers.add(marker)
        accounting_markers.add(marker)
        if arguments and raw.startswith(arguments):
            arguments = raw
        else:
            arguments = f"{arguments}{raw}"
    if arguments != encoded:
        raise RuntimeError("legacy cumulative stream reconstruction failed")


def _optimized_cumulative_tool_stream(encoded: str, fragment_chars: int) -> None:
    buffer = _StreamedToolCallBuffer(index=0)
    timeout_progress = _ToolProgressTracker()
    accounting_progress = _ToolProgressTracker()
    empty_chunk = type("Chunk", (), {"tool_calls": []})()
    for end in range(fragment_chars, len(encoded) + fragment_chars, fragment_chars):
        raw = encoded[: min(end, len(encoded))]
        call = {"index": 0, "name": "replace_document" if end == fragment_chars else "", "args": raw}
        timeout_progress.observe(empty_chunk, [call])
        accounting_progress.observe(empty_chunk, [call])
        buffer.append(call)
    if buffer.arguments != encoded or buffer.complete_arguments() is None:
        raise RuntimeError("optimized cumulative stream reconstruction failed")
    if len(timeout_progress.signatures) != 1 or len(accounting_progress.signatures) != 1:
        raise RuntimeError("optimized progress state is not bounded")


def _text_chunks(count: int) -> list[AIMessageChunk]:
    return [AIMessageChunk(content="字") for _ in range(count)]


def _legacy_fast_text_stream(chunks: list[AIMessageChunk]) -> None:
    accounting: AIMessageChunk | None = None
    response: AIMessageChunk | None = None
    timeline = {"content": ""}
    serialized_bytes = 0
    for chunk in chunks:
        accounting = chunk if accounting is None else accounting + chunk
        response = chunk if response is None else response + chunk
        text = str(chunk.content)
        timeline["content"] += text
        serialized_bytes += len(json.dumps({"event": "text_delta", "data": {"text": text}}, ensure_ascii=False))
    if accounting is None or response is None or accounting.content != response.content:
        raise RuntimeError("legacy response merge failed")
    if timeline["content"] != response.content or serialized_bytes <= 0:
        raise RuntimeError("legacy timeline reconstruction failed")


async def _optimized_fast_text_stream_async(chunks: list[AIMessageChunk]) -> None:
    accumulator = _AIMessageChunkAccumulator()
    timeline_parts: list[str] = []
    events: list[dict] = []
    batcher = _ModelDeltaBatcher(events.append, interval_seconds=60, max_chars=2_048)
    for chunk in chunks:
        accumulator.add(chunk)
        text = str(chunk.content)
        timeline_parts.append(text)
        batcher.push("text_delta", text)
    batcher.flush()
    response = accumulator.build()
    if response is None or response.content != "".join(timeline_parts):
        raise RuntimeError("optimized response merge failed")
    if "".join(event["data"]["text"] for event in events) != response.content:
        raise RuntimeError("optimized event batching changed text")
    if len(events) >= len(chunks):
        raise RuntimeError("optimized event batching did not reduce event count")


def _optimized_fast_text_stream(chunks: list[AIMessageChunk]) -> None:
    asyncio.run(_optimized_fast_text_stream_async(chunks))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-chars", type=int, default=32 * 1024)
    parser.add_argument("--tool-fragment-chars", type=int, default=32)
    parser.add_argument("--text-chunks", type=int, default=20_000)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-reduction", type=float, default=0.30)
    args = parser.parse_args()

    encoded = _tool_payload(max(1_024, args.tool_chars))
    fragment_chars = max(8, args.tool_fragment_chars)
    chunks = _text_chunks(max(1_000, args.text_chunks))

    # Warm imports and validation before either timed path.
    _optimized_cumulative_tool_stream(encoded, fragment_chars)
    _optimized_fast_text_stream(chunks[:1_000])

    cumulative_tool = _scenario_report(
        _measure(lambda: _legacy_cumulative_tool_stream(encoded, fragment_chars), args.rounds),
        _measure(lambda: _optimized_cumulative_tool_stream(encoded, fragment_chars), args.rounds),
    )
    fast_text = _scenario_report(
        _measure(lambda: _legacy_fast_text_stream(chunks), args.rounds),
        _measure(lambda: _optimized_fast_text_stream(chunks), args.rounds),
    )
    minimum_reduction = min(
        float(cumulative_tool["local_cpu_reduction_ratio"]),
        float(fast_text["local_cpu_reduction_ratio"]),
    )
    report = {
        "measurement": "local_process_cpu_seconds",
        "external_model_wait_seconds": None,
        "rounds": max(1, args.rounds),
        "cumulative_tool_arguments": {
            "encoded_chars": len(encoded),
            "fragment_chars": fragment_chars,
            "fragments": (len(encoded) + fragment_chars - 1) // fragment_chars,
            **cumulative_tool,
        },
        "fast_text_chunks": {
            "chunks": len(chunks),
            "chunk_chars": 1,
            **fast_text,
        },
        "minimum_local_cpu_reduction_ratio": minimum_reduction,
        "meets_required_reduction": minimum_reduction >= args.require_reduction,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if minimum_reduction >= args.require_reduction else 1


if __name__ == "__main__":
    raise SystemExit(main())
