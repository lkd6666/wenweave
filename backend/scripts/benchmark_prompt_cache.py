"""Synthetic gateway comparison and isolated Agent acceptance; no real document writes.

Run from backend with its venv. Reports contain usage and hashes, never credentials,
request bodies, or customer content. --acceptance records actual calls through the
normal accounting path with a distinct cache-acceptance-* source_id.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

import app.models  # noqa: F401
from app.core.crypto import decrypt_secret
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.ai_provider import ProviderType
from app.models.model_call_record import ModelCallRecord, ModelCallSource
from app.services import chat_agent as agent
from app.services.model_call_accounting import usage_from_message
from app.services.openai_compatible_chat_model import OpenAICompatibleChatModel
from tests.test_agent_loop_end_to_end import ScriptedChatModel
from tests.test_run_compaction import _cycle

DESTINATION = Path(__file__).resolve().parents[2] / "outputs/cache-optimization-20261012"


class CaptureModel(ScriptedChatModel):
    schemas: list[dict] = []

    def bind_tools(self, tools, **kwargs):
        self.schemas = [convert_to_openai_tool(tool) for tool in tools]
        return super().bind_tools(tools, **kwargs)


async def capture(enabled: bool) -> list[dict]:
    source = "<section><h1>缓存验收</h1><p>first paragraph</p><p>second paragraph</p></section>"
    session = agent.HtmlEditSession(source)
    blocks = [next(block for block in session.search(word)["results"] if block["tag"] == "p")
              for word in ("first", "second")]
    details = session.read_blocks([block["block_id"] for block in blocks])["blocks"]
    hashes = {block["block_id"]: block["expected_hash"] for block in details}
    script = [{"tool": ("get_document_map", {})},
              {"tools": [("search_html", {"query": "paragraph"}),
                         ("read_blocks", {"block_ids": [block["block_id"] for block in blocks]})]},
              {"tool": ("get_document_map", {})}]
    revisions = [session.workspace().revision, agent.HtmlWorkspace.revision_for(source.replace("first", "FIRST"))]
    for block, revision, replacement in zip(blocks, revisions, ("FIRST paragraph", "SECOND paragraph")):
        script.append({"tool": ("apply_html_patch", {"revision": revision, "operations": [{
            "block_id": block["block_id"], "expected_hash": hashes[block["block_id"]],
            "mode": "replace_inner", "html": replacement,
        }]})})
    script.append({"text": "完成"})
    model = CaptureModel(script=script, seen_messages=[], seen_message_counts=[])
    events = [event async for event in agent.run_agent_loop(
        model, "合成缓存轨迹", source, "只将 first 改为 FIRST、second 改为 SECOND，保留其余正文。",
        session.document_map(), None, [], session=session, prompt_cache_enabled=enabled,
        provider_type="openai_responses",
        tool_protocol="v1",
    )]
    assert events[-1]["event"] == "final"
    assert "FIRST paragraph" in session.html and "SECOND paragraph" in session.html
    assert not any(event["event"] == "tool_result" and event["data"].get("status") == "error" for event in events)
    captured = [{"phase": ("initial", "read", "read", "write", "write", "after_writes")[index],
                 "messages": messages, "tools": model.schemas}
                for index, messages in enumerate(model.seen_messages)]

    # A separate long tool transcript forces one actual compaction in each path.
    pending = AIMessage(content="", tool_calls=[{"id": "question", "name": "ask_user", "args": {}}])
    resume = [SystemMessage(content="旧格式系统"), HumanMessage(content="保留正文并调整排版"),
              *(message for index in range(8) for message in _cycle(index, payload_blocks=3)), pending]
    compact_model = CaptureModel(script=[{"text": "完成"}], seen_messages=[], seen_message_counts=[])
    summary = {field: "保留已完成调整" if field == "completed" else "" for field in agent._RUNTIME_SUMMARY_FIELDS}
    compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(summary))))
    fixed = agent.build_system_message(model, "合成缓存轨迹", session.html, static_only=True)
    state = HumanMessage(content=agent._RUNTIME_CONTEXT_HEADER + agent.build_volatile_system_prompt(
        "合成缓存轨迹", session.html, session.document_map()))
    budget = sum(agent._provider_message_tokens(message, agent.PROVIDER_TOKEN_ESTIMATE_SAFETY_MULTIPLIER)
                 for message in [fixed, state, resume[1], *resume[-6:]]) + 1500
    # Same budget and transcript in both paths. Actual schemas travel to gateway.
    with patch.object(agent, "_agent_tool_schema_tokens", return_value=0):
        compact_events = [event async for event in agent.run_agent_loop(
            compact_model, "合成缓存轨迹", session.html, "保留正文并调整排版", session.document_map(), None, [],
            session=session, prompt_cache_enabled=enabled, provider_type="openai_responses",
            resume_messages=resume, resume_tool_result={"tool_call_id": "question", "content": "确认"},
            compaction_model=compactor, run_input_budget_tokens=budget,
            tool_protocol="v1",
        )]
    assert compact_events[-1]["event"] == "final"
    compactor.ainvoke.assert_awaited_once()
    captured.append({"phase": "compactor", "messages": compactor.ainvoke.call_args.args[0], "tools": []})
    captured.append({"phase": "after_compaction", "messages": compact_model.seen_messages[0], "tools": compact_model.schemas})
    return captured


def totals(rows):
    inputs = sum(row["input_tokens"] for row in rows)
    reads = sum(row["cache_read_tokens"] for row in rows)
    return {"calls": len(rows), "input_tokens": inputs, "output_tokens": sum(row["output_tokens"] for row in rows),
            "cache_read_tokens": reads, "cache_write_tokens": sum(row["cache_write_tokens"] for row in rows),
            "uncached_input_tokens": inputs - reads, "weighted_hit_rate": reads / inputs if inputs else 0,
            "median_seconds": statistics.median(row["seconds"] for row in rows) if rows else None}


def load_model(db):
    model = db.get(AIModel, 40)
    assert model and model.model_name == "gpt-6.1-sol"
    assert model.provider.provider_type == ProviderType.OPENAI_RESPONSES
    assert urlsplit(model.provider.base_url).hostname in {"naiccc.com", "api.naiccc.com"}
    return model


async def compare(recheck_compaction: bool = False):
    trajectories = {"legacy": await capture(False), "stable_prefix": await capture(True)}
    with SessionLocal() as db:
        model = load_model(db)
        url = model.provider.base_url.rstrip("/") + "/responses"
        headers = {"Authorization": "Bearer " + decrypt_secret(model.provider.api_key_encrypted)}
        key = agent.build_agent_prompt_cache_key(model.provider, SimpleNamespace(
            id=model.id, model_name=model.model_name, prompt_cache_enabled=True), 1)
        transport = OpenAICompatibleChatModel(model=model.model_name, api_key="synthetic-payload-only",
                                              use_responses_api=True, max_completion_tokens=256)
    rows = ([row for row in json.loads((DESTINATION / "gateway-comparison.json").read_text(encoding="utf-8"))["rows"]
             if row["phase"] not in {"compactor", "after_compaction"}] if recheck_compaction else [])
    real_summaries = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        for index in range(6 if recheck_compaction else 0, len(trajectories["legacy"])):
            for strategy in ("legacy", "stable_prefix"):
                item = trajectories[strategy][index]
                payload = transport._get_request_payload(
                    item["messages"], **({"tools": item["tools"], "tool_choice": "none"} if item["tools"] else {})
                )
                payload.update(stream=True, reasoning={"effort": "low"})
                if item["phase"] == "compactor":
                    payload["max_output_tokens"] = 4096
                if strategy == "stable_prefix" and item["phase"] != "compactor":
                    payload["prompt_cache_key"] = key
                assert agent.RUNTIME_CONTEXT_MARKER not in json.dumps(payload)
                assert "prompt_cache_breakpoint" not in json.dumps(payload)
                started = time.monotonic()
                print(json.dumps({"request": strategy, "phase": item["phase"], "tools": len(item["tools"])}), flush=True)
                for attempt in range(2):
                    try:
                        data = None
                        first_progress = None
                        async with client.stream("POST", url, headers=headers, json=payload) as response:
                            if not response.is_success:
                                raise RuntimeError(f"synthetic gateway rejected {strategy}/{item['phase']}: HTTP {response.status_code}")
                            async for line in response.aiter_lines():
                                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                                    continue
                                event = json.loads(line[5:].strip())
                                event_type = str(event.get("type") or "")
                                if first_progress is None and event.get("delta") and event_type.endswith(".delta"):
                                    first_progress = time.monotonic() - started
                                if event_type in {"response.completed", "response.incomplete"}:
                                    data = event.get("response")
                        if data is None:
                            raise RuntimeError("synthetic gateway stream ended without usage")
                        if item["phase"] == "compactor":
                            text = "".join(str(content.get("text") or "")
                                           for output in data.get("output", []) for content in output.get("content", [])
                                           if content.get("type") == "output_text")
                            real_summaries[strategy] = agent._parse_runtime_summary(AIMessage(content=text), 1500)
                            following = trajectories[strategy][index + 1]["messages"]
                            for message in following[1:]:
                                if str(message.content).startswith("以下是较早工具循环的模型生成工作摘要。"):
                                    message.content = str(message.content).split("\n", 1)[0] + "\n" + real_summaries[strategy]
                        break
                    except httpx.TransportError as exc:
                        print(json.dumps({"transport_error": type(exc).__name__, "attempt": attempt + 1}), flush=True)
                        if attempt:
                            raise RuntimeError("bounded synthetic comparison transport failed") from None
                usage = usage_from_message(SimpleNamespace(response_metadata={"usage": data.get("usage")}))
                assert usage is not None, "gateway usage missing"
                row = {"strategy": strategy, "phase": item["phase"], **usage.__dict__,
                       "seconds": round(time.monotonic() - started, 3),
                       "first_progress_seconds": round(first_progress, 3) if first_progress is not None else None,
                       "system_hash": agent._cache_fingerprint(item["messages"][0].content),
                       "service_tier": data.get("service_tier")}
                rows.append(row)
                print(json.dumps(row), flush=True)
                (DESTINATION / "gateway-comparison-progress.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    aggregate = {strategy: totals([row for row in rows if row["strategy"] == strategy]) for strategy in trajectories}
    legacy, stable = aggregate["legacy"], aggregate["stable_prefix"]
    checks = {"uncached_input_lower": stable["uncached_input_tokens"] < legacy["uncached_input_tokens"],
              "input_growth_at_most_5_percent": stable["input_tokens"] <= legacy["input_tokens"] * 1.05,
              "compactions_equal": True, "scripted_edit_errors": 0,
              "compactor_json_valid": len(real_summaries) == 2,
              "after_compaction_fixed_rules_cached": any(row["cache_read_tokens"] > 4480 for row in rows
                    if row["strategy"] == "stable_prefix" and row["phase"] == "after_compaction"),
              "revision_changed_cache_reused": any(row["cache_read_tokens"] > 0 for row in rows
                                                    if row["strategy"] == "stable_prefix" and row["phase"] == "after_writes")}
    report = {"kind": "synthetic identical projection replay, including compactor input/output",
              "aggregate": aggregate, "acceptance": checks, "rows": rows}
    (DESTINATION / "gateway-comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"aggregate": aggregate, "acceptance": checks}), flush=True)
    assert all(checks[name] for name in ("uncached_input_lower", "input_growth_at_most_5_percent",
                                       "revision_changed_cache_reused", "compactor_json_valid", "after_compaction_fixed_rules_cached"))


async def acceptance():
    with SessionLocal() as db:
        model = load_model(db)
        assert model.prompt_cache_enabled, "enable only after comparison passes"
        key = agent.build_agent_prompt_cache_key(model.provider, model, 0)
        chat_model, _ = agent.build_chat_model(model.provider, model, thinking_mode="auto", thinking_effort="low", streaming=True,
                                             max_completion_tokens=1536, max_retries=0, request_timeout_seconds=90,
                                             prompt_cache_key=key)
        compactor = agent.build_compaction_model(model.provider, model)
        input_budget = model.context_compaction_threshold_tokens
    prefix = "cache-acceptance-" + str(int(time.time()))
    allowed = {"get_document_map", "search_html", "read_blocks", "apply_html_patch", "update_task_plan"}
    original_bind = agent._bind_tools_with_prompt_cache
    def bind_local_only(model, tools):
        return original_bind(model, [tool for tool in tools if tool.name in allowed])
    completed_runs = []
    observed = 0
    for index in range(15):
        source = f"<section><h1>合成验收 {index}</h1><p>alpha paragraph {index}</p><p>beta paragraph {index}</p></section>"
        session = agent.HtmlEditSession(source)
        started = time.monotonic()
        with patch.object(agent, "_bind_tools_with_prompt_cache", side_effect=bind_local_only):
            events = [event async for event in agent.run_agent_loop(
                chat_model, f"合成验收 {index}", source,
                "只将 alpha paragraph 中的 alpha 改成 ALPHA，将 beta paragraph 中的 beta 改成 BETA，保留所有其他文字和结构。"
                "先分别读取两个段落；两次局部写入依次提交，每次写入采用当时的最新 revision 和 hash。完成后简短回复。",
                session.document_map(), None, [], session=session, provider_type="openai_responses",
                prompt_cache_enabled=True, model_id=40, trace_id=f"{prefix}-{index}", compaction_model=compactor,
                run_input_budget_tokens=input_budget,
                tool_protocol="v1",
            )]
        expected = source.replace("alpha", "ALPHA").replace("beta", "BETA")
        successful = bool(events and events[-1]["event"] == "final" and session.html == expected)
        if not successful:
            raise RuntimeError(f"isolated Agent edit failed at fixture {index}; inspect synthetic log before rollout")
        with SessionLocal() as db:
            records = db.query(ModelCallRecord).filter(ModelCallRecord.source_id.like(prefix + "%")).all()
            agents = [record for record in records if record.source == ModelCallSource.AGENT and record.usage_reported]
            observed = len(agents)
            stats = totals([{**{name: getattr(record, name) or 0 for name in
                               ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
                             "seconds": (record.finished_at - record.started_at).total_seconds()} for record in agents])
            compact = [record for record in records if record.source != ModelCallSource.AGENT]
        completed_runs.append({"fixture": index, "correct_edit": successful, "seconds": round(time.monotonic() - started, 3)})
        report = {"kind": "isolated actual Agent calls, synthetic documents, distinct source_id; not production traffic",
                  "source_id_prefix": prefix, "reported_agent_calls": observed, "agent_usage": stats,
                  "compaction_calls": len(compact), "runs": completed_runs}
        (DESTINATION / "agent-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"fixture": index, "reported_agent_calls": observed, "agent_usage": stats}), flush=True)
        if observed >= 30:
            return
    raise RuntimeError(f"only {observed} reported Agent calls after bounded fixtures")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--recheck-compaction", action="store_true")
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(acceptance() if args.acceptance else compare(args.recheck_compaction))
