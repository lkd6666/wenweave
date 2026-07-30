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


def recover_interrupted_turn(events: Iterable[object], terminal_notice: str) -> RecoveredAgentTurn:
    """Convert replayable SSE events into a terminal, historical assistant turn.

    Agent events are written before they are sent to the browser.  A process
    restart can therefore interrupt the normal terminal-message write while
    still leaving enough information to present everything completed so far.
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
            tool = next((item for item in tool_calls if item["id"] == tool_id), None)
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
                tool["name"] = _text(data.get("name")) or tool["name"]
                if isinstance(data.get("arguments"), dict):
                    tool["arguments"] = data["arguments"]
                if not data.get("preparing"):
                    tool["preparing"] = False
            continue
        if event == "tool_result":
            tool_name = _text(data.get("name"))
            tool = next(
                (item for item in reversed(tool_calls) if item["name"] == tool_name and item["status"] == "running"),
                None,
            )
            if tool is not None:
                result = _text(data.get("result"))
                tool["result"] = result
                tool["status"] = "error" if result.startswith("错误") else "success"
                tool["preparing"] = False
                tool["html_changed"] = bool(data.get("html"))
                tool["activity"] = data.get("activity") if isinstance(data.get("activity"), dict) else None

    finish_active_text_block()
    for tool in tool_calls:
        settle_tool(tool)
    for block in turn_blocks:
        if block.get("state") == "active":
            block["state"] = "done"
        tool = block.get("tool")
        if isinstance(tool, dict):
            settle_tool(tool)

    recovered_event_context = bool(turn_blocks or tool_calls or reasoning_parts)
    _append_terminal_notice(turn_blocks, terminal_notice)
    content = next(
        (str(block.get("content", "")) for block in reversed(turn_blocks) if block.get("type") == "content"),
        terminal_notice,
    )
    reasoning = "".join(reasoning_parts)
    return RecoveredAgentTurn(
        content=content,
        tool_calls=tool_calls,
        reasoning_trace={"status": "complete" if reasoning else "idle", "content": reasoning, "detail": ""},
        turn_blocks=turn_blocks,
        recovered_event_context=recovered_event_context,
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
