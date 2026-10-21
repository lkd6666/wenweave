"""Synthetic context preflight benchmark; excludes network and model wait."""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.services import agent_context
from app.services.agent_context import AgentContextBuilder
from app.services.chat_agent import build_static_system_prompt, editor_tool_schema_tokens
from app.services.html_workspace import HtmlWorkspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=80)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--ui-payload-kib", type=int, default=0,
                        help="Size per historical HTML snapshot for a separate allocation comparison")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        session = ChatSession(document_id=1, title="synthetic benchmark")
        model = AIModel(provider_id=1, model_name="test", display_name="test",
                        context_window_tokens=258_000, context_compaction_threshold_tokens=176_000,
                        max_output_tokens=12_000, tool_result_max_tokens=4_000)
        db.add_all([session, model])
        db.flush()
        ui_html = "<p>" + "x" * (max(0, args.ui_payload_kib) * 1024) + "</p>" if args.ui_payload_kib else None
        for turn in range(args.turns):
            row = ChatMessage(document_id=1, session_id=session.id, role=MessageRole.USER,
                              content=f"调整第 {turn} 段的排版。", html_before=ui_html, html_after=ui_html)
            db.add(row)
            db.flush()
            db.add(ChatContextEvent(document_id=1, session_id=session.id, message_id=row.id,
                                    ordinal=0, kind=ContextEventKind.USER,
                                    payload_json=json.dumps({"content": row.content}, ensure_ascii=False)))
            row = ChatMessage(document_id=1, session_id=session.id, role=MessageRole.ASSISTANT,
                              content="已调整", html_before=ui_html, html_after=ui_html)
            db.add(row)
            db.flush()
            for ordinal in range(4):
                call_id = f"call-{turn}-{ordinal}"
                db.add_all([
                    ChatContextEvent(document_id=1, session_id=session.id, message_id=row.id,
                                     ordinal=ordinal * 2, kind=ContextEventKind.ASSISTANT,
                                     payload_json=json.dumps({"content": "", "tool_calls": [{"id": call_id, "name": "read_blocks", "args": {"block_ids": ["b-1"]}}]})),
                    ChatContextEvent(document_id=1, session_id=session.id, message_id=row.id,
                                     ordinal=ordinal * 2 + 1, kind=ContextEventKind.TOOL,
                                     payload_json=json.dumps({"tool_call_id": call_id, "name": "read_blocks", "content": json.dumps({"text": "固定基准测试段落，检查上下文性能。" * 40}, ensure_ascii=False)}, ensure_ascii=False)),
                ])
        db.commit()
        prompt = build_static_system_prompt()
        schema = editor_tool_schema_tokens("openai_compatible")
        agent_context.estimate_tokens("warmup")
        original_estimate = agent_context.estimate_tokens
        samples = []
        for _ in range(args.rounds):
            counts = {"calls": 0, "chars": 0}
            def counted(value):
                counts["calls"] += 1
                counts["chars"] += len(value)
                return original_estimate(value)
            with patch.object(agent_context, "estimate_tokens", side_effect=counted):
                started = time.process_time()
                builder = AgentContextBuilder(db, 1, session.id, model, HtmlWorkspace("<p>当前正文</p>"), None, prompt,
                                              current_request="继续", tool_schema_tokens=schema)
                stats = builder.snapshot()
                samples.append({"cpu_seconds": time.process_time() - started, **counts})
        report = {
            "measurement": "synthetic_preflight_local_process_cpu",
            "turns": args.turns, "events": stats["event_count"], "samples": samples,
            "median_cpu_seconds": statistics.median(item["cpu_seconds"] for item in samples),
            "stats": {key: stats[key] for key in ("used_tokens", "requires_compaction", "projected_used_tokens", "breakdown")},
            "static_prompt_neutral_tokens": original_estimate(prompt), "tool_schema_tokens": schema,
        }
        if args.ui_payload_kib:
            session_id, model_id = session.id, model.id
            allocation_samples = []
            # Both paths use the same optimized builder. Only the former route's
            # eager ORM history query differs, isolating avoidable allocations.
            # tracemalloc measures Python allocations, not whole-host/RSS memory.
            for eager in (True, False):
                gc.collect()
                with Session(engine) as memory_db:
                    memory_model = memory_db.get(AIModel, model_id)
                    tracemalloc.start()
                    try:
                        rows = memory_db.query(ChatMessage).filter_by(session_id=session_id).all() if eager else None
                        memory_builder = AgentContextBuilder(memory_db, 1, session_id, memory_model,
                                                             HtmlWorkspace("<p>当前正文</p>"), rows, prompt,
                                                             current_request="继续", tool_schema_tokens=schema)
                        memory_stats = memory_builder.snapshot()
                        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
                    finally:
                        tracemalloc.stop()
                    assert memory_stats["used_tokens"] == stats["used_tokens"]
                    allocation_samples.append({"history_loading": "eager_all_columns" if eager else "ledger_only",
                                               "current_python_bytes": current_bytes, "peak_python_bytes": peak_bytes})
                del rows, memory_builder
            report["history_loading_allocations"] = {
                "measurement": "tracemalloc_python_allocations_excluding_database_setup",
                "html_snapshot_kib": args.ui_payload_kib,
                "samples": allocation_samples,
            }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
