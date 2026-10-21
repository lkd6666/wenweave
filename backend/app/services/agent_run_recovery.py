"""Rebuild an interrupted Agent turn from its durable event ledger."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class RecoveredAgentTurn:
    """The persisted assistant fields reconstructed after a worker restart."""

    content: str
    tool_calls: list[dict[str, Any]]
    reasoning_trace: dict[str, str]
    turn_blocks: list[dict[str, Any]]
    recovered_event_context: bool = False

    @property
    def has_recovered_context(self) -> bool:
        return self.recovered_event_context


def replay_agent_turn(
    events: Iterable[object],
    *,
    question_timelines: dict[str, dict[str, Any]] | None = None,
) -> RecoveredAgentTurn:
    """Rebuild the visible in-flight turn from its durable event ledger.

    This intentionally leaves active text blocks and tools active.  It is used
    when a browser reconnects so persisted output can be painted immediately,
    while new SSE events continue from the ledger cursor without replaying the
    earlier response token by token.
    """
    tool_calls: list[dict[str, Any]] = []
    turn_blocks: list[dict[str, Any]] = []
    reasoning_parts: list[str] = []
    retry_checkpoint: tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]] | None = None

    def finish_active_text_block() -> None:
        if turn_blocks and turn_blocks[-1].get("type") in {"thought", "content"}:
            turn_blocks[-1]["state"] = "done"

    def append_text_block(block_type: str, value: str) -> None:
        if not value:
            return
        if turn_blocks and turn_blocks[-1].get("type") == block_type and turn_blocks[-1].get("state") == "active":
            turn_blocks[-1]["content"] += value
            return
        finish_active_text_block()
        turn_blocks.append(
            {
                "id": f"{block_type}-{len(turn_blocks) + 1}",
                "type": block_type,
                "state": "active",
                "content": value,
                "duration_ms": None,
            }
        )

    for event_row in events:
        event = str(getattr(event_row, "event", ""))
        data = _event_data(event_row)
        if event == "heartbeat" and data.get("phase") == "model_turn_started":
            retry_checkpoint = (copy.deepcopy(tool_calls), copy.deepcopy(turn_blocks), list(reasoning_parts))
            continue
        if event == "model_turn_retry":
            if retry_checkpoint is not None:
                tool_calls, turn_blocks, reasoning_parts = copy.deepcopy(retry_checkpoint)
            continue
        if event == "reasoning_delta":
            text = _text(data.get("text"))
            reasoning_parts.append(text)
            append_text_block("thought", text)
            continue
        if event == "text_delta":
            append_text_block("content", _text(data.get("text")))
            continue
        if event == "tool_call":
            finish_active_text_block()
            tool_id = _text(data.get("id")) or f"tool-{len(tool_calls) + 1}"
            replaces_id = _text(data.get("replaces_id"))
            tool = next((item for item in tool_calls if item["id"] in {tool_id, replaces_id}), None)
            if tool is None:
                tool = {
                    "id": tool_id,
                    "name": _text(data.get("name")) or "unknown",
                    "arguments": data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
                    "status": "running",
                    "preparing": bool(data.get("preparing")),
                    "result": None,
                    "html_changed": False,
                    "activity": None,
                }
                tool_calls.append(tool)
                turn_blocks.append(
                    {"id": f"block-{tool_id}", "type": "tool", "state": "done", "content": "", "tool": tool}
                )
            else:
                tool["id"] = tool_id
                tool["name"] = _text(data.get("name")) or tool["name"]
                if isinstance(data.get("arguments"), dict):
                    tool["arguments"] = data["arguments"]
                if isinstance(data.get("argument_tokens"), int):
                    tool["argument_tokens"] = max(
                        int(tool.get("argument_tokens") or 0), max(0, data["argument_tokens"])
                    )
                if not data.get("preparing"):
                    tool["preparing"] = False
            continue
        if event == "tool_result":
            tool_id = _text(data.get("id"))
            tool_name = _text(data.get("name"))
            tool = (
                next((item for item in reversed(tool_calls) if item["id"] == tool_id), None)
                if tool_id
                else next(
                    (item for item in reversed(tool_calls) if item["name"] == tool_name and item["status"] == "running"), None)
            )
            if tool is not None:
                result = _text(data.get("result"))
                tool["result"] = result
                tool["status"] = "error" if result.startswith("错误") else "success"
                tool["preparing"] = False
                tool["html_changed"] = bool(data.get("html"))
                tool["activity"] = data.get("activity") if isinstance(data.get("activity"), dict) else None
                tool["model_input"] = data.get("model_input") if isinstance(data.get("model_input"), dict) else None
                tool["read_range"] = data.get("read_range") if isinstance(data.get("read_range"), dict) else None
                tool["change_summary"] = data.get("change_summary") if isinstance(data.get("change_summary"), dict) else None
            continue
        if event == "context_compaction":
            turn_blocks.append(
                {
                    "id": _text(data.get("id")) or f"context-compaction-{len(turn_blocks) + 1}",
                    "type": "context_compaction",
                    "state": "done",
                    "content": "",
                    "duration_ms": None,
                    "tool": None,
                    "context_compaction": {
                        "summary": _text(data.get("summary")),
                        "original_tokens": max(0, int(data.get("original_tokens") or 0)),
                        "used_tokens": max(0, int(data.get("used_tokens") or 0)),
                        "summarized_cycles": max(0, int(data.get("summarized_cycles") or 0)),
                        "digested_cycles": max(0, int(data.get("digested_cycles") or 0)),
                        "dropped_cycles": max(0, int(data.get("dropped_cycles") or 0)),
                        "summary_tokens": max(0, int(data.get("summary_tokens") or 0)),
                        "durable_snapshot": bool(data.get("durable_snapshot")),
                    },
                }
            )
            continue
        if event == "user_question":
            question_id = _text(data.get("id"))
            timeline = (question_timelines or {}).get(question_id)
            if not isinstance(timeline, dict):
                timeline = data.get("timeline") if isinstance(data.get("timeline"), dict) else None
            if timeline is not None:
                candidate_tools = timeline.get("tool_calls")
                candidate_blocks = timeline.get("turn_blocks")
                candidate_reasoning = timeline.get("reasoning")
                if isinstance(candidate_tools, list):
                    tool_calls = copy.deepcopy(candidate_tools)
                if isinstance(candidate_blocks, list):
                    turn_blocks = copy.deepcopy(candidate_blocks)
                if isinstance(candidate_reasoning, dict):
                    reasoning_content = _text(candidate_reasoning.get("content"))
                    reasoning_parts = [reasoning_content] if reasoning_content else []

    recovered_event_context = bool(turn_blocks or tool_calls or reasoning_parts)
    content = next(
        (str(block.get("content", "")) for block in reversed(turn_blocks) if block.get("type") == "content"),
        "",
    )
    reasoning = "".join(reasoning_parts)
    return RecoveredAgentTurn(
        content=content,
        tool_calls=tool_calls,
        reasoning_trace={"status": "thinking" if reasoning else "idle", "content": reasoning, "detail": ""},
        turn_blocks=turn_blocks,
        recovered_event_context=recovered_event_context,
    )


def recover_interrupted_turn(events: Iterable[object], terminal_notice: str) -> RecoveredAgentTurn:
    """Convert replayable SSE events into a terminal, historical assistant turn.

    Agent events are written before they are sent to the browser.  A process
    restart can therefore interrupt the normal terminal-message write while
    still leaving enough information to present everything completed so far.
    """
    recovered = replay_agent_turn(events)
    tool_calls = recovered.tool_calls
    turn_blocks = recovered.turn_blocks

    def settle_tool(tool: dict[str, Any]) -> None:
        if tool.get("status") != "running":
            return
        tool["status"] = "error"
        tool["result"] = (
            "模型未完成工具参数生成，工具尚未执行。"
            if tool.get("preparing")
            else "服务重启前未收到该工具的执行结果。"
        )
        tool["preparing"] = False

    for block in turn_blocks:
        if block.get("state") == "active":
            block["state"] = "done"
        tool = block.get("tool")
        if isinstance(tool, dict):
            settle_tool(tool)
    for tool in tool_calls:
        settle_tool(tool)

    _append_terminal_notice(turn_blocks, terminal_notice)
    content = next(
        (str(block.get("content", "")) for block in reversed(turn_blocks) if block.get("type") == "content"),
        terminal_notice,
    )
    reasoning = str(recovered.reasoning_trace.get("content") or "")
    return RecoveredAgentTurn(
        content=content,
        tool_calls=tool_calls,
        reasoning_trace={"status": "complete" if reasoning else "idle", "content": reasoning, "detail": ""},
        turn_blocks=turn_blocks,
        recovered_event_context=recovered.recovered_event_context,
    )


def _event_data(event_row: object) -> dict[str, Any]:
    raw = getattr(event_row, "payload_json", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _append_terminal_notice(turn_blocks: list[dict[str, Any]], terminal_notice: str) -> None:
    """Keep interrupted model output visible while adding the recovery result."""
    notice = terminal_notice.strip()
    if not notice:
        return
    for block in reversed(turn_blocks):
        if block.get("type") != "content":
            continue
        previous = str(block.get("content", "")).rstrip()
        block["content"] = f"{previous}\n\n{notice}" if previous else notice
        block["state"] = "done"
        return
    turn_blocks.append(
        {
            "id": f"content-{len(turn_blocks) + 1}",
            "type": "content",
            "state": "done",
            "content": notice,
            "duration_ms": None,
        }
    )
