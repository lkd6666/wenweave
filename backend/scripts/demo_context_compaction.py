"""Offline context-compaction example; no network or production database access.

Run from backend: python scripts/demo_context_compaction.py
The deterministic summarizer demonstrates budgeting, not real-model recall.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.services.chat_agent import _run_message_tokens, _provider_message_tokens, compact_run_messages_with_model
from app.services.context_projection import bind_context_tool_result, tool_receipt
from app.services.tool_output_store import ToolOutputStore


def tool_cycle(index: int):
    call_id = f"demo-{index}"
    return [
        AIMessage(content="", tool_calls=[{
            "id": call_id, "name": "read_file", "args": {"path": "/article.html"},
        }]),
        ToolMessage(name="read_file", tool_call_id=call_id, content=json.dumps({
            "path": "/article.html",
            "revision": f"r{index}",
            "content": "\n".join(f"<p>第 {line} 段：" + "排版示例内容" * 20 + "</p>" for line in range(40)),
        }, ensure_ascii=False)),
    ]


class DemoCompactor:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(content=json.dumps({
            "objective": "完成全文标题层级调整",
            "constraints": "保留正文；标题使用蓝色",
            "decisions": "编辑前重读当前文件",
            "completed": "已检查早期段落",
            "active_work": "继续检查最近读取的段落",
            "blockers": "",
            "next_steps": "核对最新文件后提交局部修改",
            "source_refs": "",
        }, ensure_ascii=False))


async def demonstrate():
    messages = [SystemMessage(content="保留原文，按用户要求排版。" * 50),
                HumanMessage(content="标题使用蓝色"), AIMessage(content="已记录"),
                HumanMessage(content="请调整全文标题层级")]
    for index in range(5):
        messages.extend(tool_cycle(index))
    multiplier = 1.6
    reserved = 4000  # Example tool-schema and live-state cost.
    trigger = _run_message_tokens(messages, multiplier, 0)
    _, previous = await compact_run_messages_with_model(
        messages, trigger, DemoCompactor(), token_estimate_multiplier=multiplier, reserved_tokens=reserved)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    store = ToolOutputStore(document_id=1, session_id=1, run_id="offline-demo")
    def bind(items):
        return [bind_context_tool_result(item, tool_name=item.name, max_tokens=16_000, store=store)
                if isinstance(item, ToolMessage) else item for item in items]
    try:
        fixture_time = datetime(2026, 11, 3, 0, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.tool_output_store.SessionLocal", factory), patch(
            "app.services.tool_output_store.uuid4", side_effect=[uuid5(NAMESPACE_URL, f"context-demo-{i}") for i in range(10)]
        ), patch("app.services.tool_output_store._now", return_value=fixture_time), patch(
            "app.services.context_projection.datetime", wraps=datetime
        ) as fixture_clock:
            fixture_clock.now.return_value = fixture_time
            bound = bind(messages)
            compactor = DemoCompactor()
            outgoing, stats = await compact_run_messages_with_model(
                bound, trigger, compactor, token_estimate_multiplier=multiplier, reserved_tokens=reserved)
            before_calls = compactor.calls
            continuation_input = [*outgoing, *bind(tool_cycle(99)), *bind(tool_cycle(100))]
            continued, continuation = await compact_run_messages_with_model(
                continuation_input, trigger, compactor,
                token_estimate_multiplier=multiplier, reserved_tokens=reserved)
            # Exercise real paging of the removed latest result, including its tail.
            receipt = tool_receipt(bound[-1])
            parts, cursor = [], None
            with factory() as db:
                while True:
                    page = json.loads(store.read_page(db, output_id=receipt["output_id"], cursor=cursor, max_tokens=700))
                    parts.append(page["content"])
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
            recovery_exact = "".join(parts) == messages[-1].content
    finally:
        engine.dispose()
    fixed_tokens = reserved + _run_message_tokens([messages[0], messages[3]], multiplier, 0)
    summary_tokens = sum(_provider_message_tokens(item, multiplier) for item in outgoing
                         if isinstance(item, SystemMessage) and item is not messages[0])
    return {
        "fixture": "synthetic; deterministic summarizer; provider estimates, not billed usage",
        "same_raw_fixture_tokens": trigger + reserved,
        "previous_unconditional_latest_cycle_tokens": previous["used_tokens"] + reserved,
        "archive_handle_overhead_tokens": stats["original_tokens"] - trigger,
        "before_total_tokens": stats["original_tokens"] + reserved,
        "after_total_tokens": stats["used_tokens"] + reserved,
        "target_total_tokens": stats["compaction_target_tokens"] + reserved,
        "saved_percent": round(100 * (stats["original_tokens"] - stats["used_tokens"]) / (stats["original_tokens"] + reserved), 1),
        "headroom_tokens": stats["headroom_tokens"],
        "required_context_tokens": stats["required_context_tokens"],
        "token_components_after": {"fixed_rules_current_request_schema_live_state": fixed_tokens,
                                   "summary_wrapper_and_recovery_receipts": summary_tokens,
                                   "verbatim_tool_results": 0},
        "source_batch_count": stats["source_batch_count"],
        "original_messages": len(messages),
        "outgoing_messages": len(outgoing),
        "next_two_cycles_requires_compaction": continuation["compacted"],
        "next_two_cycles_summary_calls": compactor.calls - before_calls,
        "next_two_cycles_total_tokens": _run_message_tokens(continued, multiplier, 0) + reserved,
        "continuation_messages_unchanged": [item.model_dump() for item in continued] == [item.model_dump() for item in continuation_input],
        "exact_archived_output_recovered": recovery_exact,
        "latest_cycle_checkpointed": stats["latest_cycle_checkpointed"],
        "summary": json.loads(stats["summary"]),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(demonstrate()), ensure_ascii=False, indent=2))
