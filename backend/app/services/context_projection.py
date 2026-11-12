"""Retrieval-backed checkpoints, separate from the canonical transcript.

Receipts authorize checkpointing at a compaction boundary, never per-turn
rewrites of the delivered prefix. Controls, errors and images stay protected.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.services.token_budget import estimate_tokens
from app.services.tool_output_store import ToolOutputStore


RECEIPT_KEY = "context_output_receipt"
READ_TOOLS = {"read_file", "search_files", "list_files", "read_blocks", "search_html", "get_document_map"}
WRITE_TOOLS = {"edit_file", "apply_patch", "write_file", "apply_html_patch", "replace_document"}
_BULK_FIELDS = {"content", "files", "results", "matches", "blocks", "preview"}
_RETRIEVAL_RULE = (
    "原文已外置，需要精确内容时启用 history 工具组并 read_tool_output(output_id)。"
    "文件内容与定位是历史版本；编辑前 read_file 当前文件，过期引用重新查询源工具。"
)


def _json_object(content: object) -> dict | None:
    if not isinstance(content, str):
        return None
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _has_problem(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("ok") is False or value.get("valid") is False or value.get("isValid") is False:
            return True
        if any(value.get(key) for key in ("error", "errors", "warning", "warnings", "blocked")):
            return True
        return any(_has_problem(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_problem(item) for item in value)
    return False


def _receipt(content: object, name: str, output_id: str, expires_at: str) -> dict | None:
    payload = _json_object(content)
    if payload is None or _has_problem(payload):
        return None
    if name not in READ_TOOLS | WRITE_TOOLS | {"read_tool_output"}:
        return None
    if name in WRITE_TOOLS and payload.get("ok") is not True:
        return None
    # Write receipts preserve every check and status; only the large call
    # arguments are removed by a successful semantic checkpoint later.
    facts = dict(payload) if name in WRITE_TOOLS else {
        key: value for key, value in payload.items() if key not in _BULK_FIELDS
    }
    for key in ("output_id", "expires_at", "next_step"):
        facts.pop(key, None)
    return {"context_output_evicted": True, "tool": name, "output_id": output_id, "source_ref": f"tool:{output_id}",
            "expires_at": expires_at, "facts": facts, "next_step": _RETRIEVAL_RULE}


def bind_context_tool_result(message: ToolMessage, *, tool_name: str,
                             max_tokens: int, store: ToolOutputStore | None) -> ToolMessage:
    """Archive eligible output before its first consumption, without hiding it.

    A large first result still uses the store's normal bounded preview. Failed
    archival yields no receipt, so the normal compactor retains the live result.
    Recovery pages reuse the original object, never create recursive archives.
    """
    content = message.content
    if not isinstance(content, str):
        return message
    payload = _json_object(content)
    if tool_name == "read_tool_output":
        receipt = _receipt(content, tool_name, str((payload or {}).get("output_id") or ""),
                           str((payload or {}).get("expires_at") or ""))
        return message.model_copy(update={"additional_kwargs": {**message.additional_kwargs, RECEIPT_KEY: receipt}}) if receipt else message
    template = _receipt(content, tool_name, "toolout-00000000-0000-0000-0000-000000000000", "2000-01-01T00:00:00+00:00")
    archive = (message.status != "error" and template is not None
               and (tool_name in WRITE_TOOLS or estimate_tokens(json.dumps(template, ensure_ascii=False)) < estimate_tokens(content)))
    if store is None:
        binding = ToolOutputStore.preview_without_storage(content=content, max_preview_tokens=max_tokens)
    else:
        binding = store.bind(tool_call_id=str(message.tool_call_id or ""), tool_name=tool_name,
                             content=content, max_preview_tokens=max_tokens,
                             force_store=archive, inline_when_fits=archive)
    receipt = (_receipt(content, tool_name, binding.output_id, binding.expires_at)
               if binding.stored and binding.output_id and archive else None)
    visible = binding.content
    # Include the handle in the visible event when it fits. Never turn a
    # contiguous source page into head/tail preview solely for handle overhead:
    # its offsets/cursor are required for exact editing. In that case the full
    # page remains in the event and the receipt exposes it at the checkpoint.
    if receipt and visible == content and payload is not None:
        visible = json.dumps({**payload, "output_id": binding.output_id, "expires_at": binding.expires_at},
                             ensure_ascii=False, separators=(",", ":"))
        if estimate_tokens(visible) > max_tokens:
            visible = content
    if receipt:
        receipt["delivery"] = "preview" if (_json_object(visible) or {}).get("truncated") else "inline"
    return message.model_copy(update={"content": visible, "additional_kwargs": {
        **message.additional_kwargs, **({RECEIPT_KEY: receipt} if receipt else {}),
    }})


def tool_receipt(message: BaseMessage) -> dict | None:
    if not isinstance(message, ToolMessage) or message.status == "error" or not isinstance(message.content, str):
        return None
    receipt = message.additional_kwargs.get(RECEIPT_KEY)
    if not isinstance(receipt, dict) or not receipt.get("output_id"):
        return None
    try:
        expiry = datetime.fromisoformat(receipt["expires_at"])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return receipt


def cycle_checkpoint_receipts(cycle: Sequence[BaseMessage]) -> list[dict] | None:
    """A latest cycle can be summarized only at a complete, recoverable boundary."""
    if not cycle or not isinstance(cycle[0], AIMessage):
        return None
    calls = cycle[0].tool_calls
    ids = [str(call.get("id") or "") for call in calls]
    if not ids or any(not key for key in ids) or len(set(ids)) != len(ids):
        return None
    if len(cycle) != len(ids) + 1 or not isinstance(cycle[0].content, str):
        return None
    names = {str(call["id"]): call["name"] for call in calls}
    receipts = []
    answered = set()
    for message in cycle[1:]:
        receipt = tool_receipt(message)
        if receipt is None or message.tool_call_id in answered or message.tool_call_id not in names:
            return None
        # Explicit recovery must be consumed by the main model before eviction;
        # otherwise summary -> re-read -> summary can starve exact content.
        if names[message.tool_call_id] == "read_tool_output" or receipt["tool"] != names[message.tool_call_id]:
            return None
        answered.add(message.tool_call_id)
        receipts.append(receipt)
    return receipts if answered == set(ids) else None
