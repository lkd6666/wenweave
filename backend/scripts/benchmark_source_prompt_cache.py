"""Replay identical v2 source trajectories with caching optimization off/on.

Default validates projections offline. --live replays synthetic requests to
model 40 without executing model-generated tools or writing business documents.
Reports contain usage and fingerprints, not prompts or credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import app.models  # noqa: F401
from app.core.crypto import decrypt_secret
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.ai_provider import ProviderType
from app.services import chat_agent as agent
from app.services.model_call_accounting import usage_from_message
from app.services.openai_compatible_chat_model import OpenAICompatibleChatModel
from app.services.source_agent import create_source_workspace
from tests.test_source_prompt_cache import CaptureSourceModel

DESTINATION = Path(__file__).resolve().parents[2] / "outputs/source-cache-adaptation-20261012"


async def capture(enabled: bool, key: str) -> list[dict]:
    source = "<section><p>first paragraph</p><p>second paragraph</p></section>"
    session = agent.HtmlEditSession(source)
    second_revision = agent.HtmlWorkspace.revision_for(source.replace("first", "FIRST"))
    script = [
        {"tool": ("read_file", {"path": "/article.html"})},
        {"tool": ("enable_tool_groups", {"groups": ["history"]})},
        {"tool": ("read_file", {"path": "/article.html"})},
        {"tool": ("edit_file", {"path": "/article.html", "revision": session.source_file().revision,
                                 "edits": [{"old_text": "first", "new_text": "FIRST"}]})},
        {"tool": ("edit_file", {"path": "/article.html", "revision": second_revision,
                                 "edits": [{"old_text": "second", "new_text": "SECOND"}]})},
        {"tool": ("read_file", {"path": "/article.html"})},
        {"text": "完成"},
    ]
    model = CaptureSourceModel(script=script, seen_messages=[], seen_message_counts=[],
                               seen_schemas=[], seen_cache_keys=[])
    events = [item async for item in agent.run_agent_loop(
        model, "源码缓存合成验收", source, "只将 first 改为 FIRST、second 改为 SECOND，保留其余内容。",
        create_source_workspace(session).map_payload(), None, [], session=session,
        tool_protocol="v2", provider_type="openai_responses", prompt_cache_enabled=enabled,
        prompt_cache_key=key if enabled else None)]
    assert events[-1]["event"] == "final"
    assert session.html == source.replace("first", "FIRST").replace("second", "SECOND")
    phases = ("initial", "read", "group_loaded", "read_after_group", "write", "after_writes", "read_after_writes")
    rows = [{"phase": phase, "messages": messages, "tools": schemas, "cache_key": cache_key}
            for phase, messages, schemas, cache_key in zip(phases, model.seen_messages, model.seen_schemas, model.seen_cache_keys)]

    pending = AIMessage(content="", tool_calls=[{"id": "question", "name": "ask_user", "args": {}}])
    cycles = []
    for index in range(8):
        call_id = f"read-{index}"
        cycles.extend([AIMessage(content="", tool_calls=[{"id": call_id, "name": "read_file",
            "args": {"path": "/article.html"}}]),
            ToolMessage(content=json.dumps({"path": "/article.html", "revision": "old",
                "content": "历史源码中文🙂 " * 600}, ensure_ascii=False), tool_call_id=call_id, name="read_file")])
    resume = [SystemMessage(content="old"), HumanMessage(content="只调整授权文字"), *cycles, pending]
    config = SimpleNamespace(prompt_cache_enabled=enabled, tool_result_max_tokens=4096,
        provider=SimpleNamespace(provider_type=SimpleNamespace(value="openai_responses")))
    fixed, state = agent.runtime_context_budget_factory(config, "源码缓存合成验收", session.html,
        tool_protocol="v2", loaded_tool_groups=["history"])({})
    schema = agent.editor_tool_schema_tokens("openai_responses", tool_protocol="v2", loaded_tool_groups=("history",))
    required = sum(agent._provider_message_tokens(item, 1.6) for item in
                   [SystemMessage(content=fixed), HumanMessage(content=state), resume[1], *resume[-6:]])
    compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
        field: "保留已完成调整" if field == "completed" else "" for field in agent._RUNTIME_SUMMARY_FIELDS}))))
    compact_model = CaptureSourceModel(script=[{"tool": ("read_file", {"path": "/article.html"})}, {"text": "完成"}],
        seen_messages=[], seen_message_counts=[], seen_schemas=[], seen_cache_keys=[])
    compact_events = [item async for item in agent.run_agent_loop(
        compact_model, "源码缓存合成验收", session.html, "只调整授权文字", create_source_workspace(session).map_payload(),
        None, [], session=session, tool_protocol="v2", loaded_tool_groups=["history"],
        provider_type="openai_responses", prompt_cache_enabled=enabled, prompt_cache_key=key if enabled else None,
        resume_messages=resume, resume_tool_result={"tool_call_id": "question", "content": "确认"},
        compaction_model=compactor, run_input_budget_tokens=required + schema + 1500)]
    assert compact_events[-1]["event"] == "final"
    compactor.ainvoke.assert_awaited_once()
    rows.append({"phase": "compactor", "messages": compactor.ainvoke.call_args.args[0], "tools": [], "cache_key": None})
    for phase, messages, schemas, cache_key in zip(("after_compaction", "read_after_compaction"),
            compact_model.seen_messages, compact_model.seen_schemas, compact_model.seen_cache_keys):
        rows.append({"phase": phase, "messages": messages, "tools": schemas, "cache_key": cache_key})
    return rows


def totals(rows):
    inputs = sum(row["input_tokens"] for row in rows)
    reads = sum(row["cache_read_tokens"] for row in rows)
    return {"calls": len(rows), "input_tokens": inputs, "cache_read_tokens": reads,
            "uncached_input_tokens": inputs - reads,
            "weighted_hit_rate": reads / inputs if inputs else 0,
            "output_tokens": sum(row["output_tokens"] for row in rows)}


async def main(live: bool, destination: Path = DESTINATION):
    destination.mkdir(parents=True, exist_ok=True)
    key = "yb-agent-v1-p0-m40-s1"
    if live:
        with SessionLocal() as db:
            model = db.get(AIModel, 40)
            assert model and model.is_enabled and model.prompt_cache_enabled
            assert model.model_name == "gpt-6.1-sol" and model.provider.provider_type == ProviderType.OPENAI_RESPONSES
            assert urlsplit(model.provider.base_url).hostname in {"naiccc.com", "api.naiccc.com"}
            key = agent.build_agent_prompt_cache_key(model.provider, model, 1)
            url = model.provider.base_url.rstrip("/") + "/responses"
            headers = {"Authorization": "Bearer " + decrypt_secret(model.provider.api_key_encrypted)}
    trajectories = {"legacy": await capture(False, key), "stable_prefix": await capture(True, key)}
    checks = {"exact_source_edits": True, "equal_compactions": True,
              "stable_schemas_after_group": trajectories["stable_prefix"][2]["tools"] == trajectories["stable_prefix"][6]["tools"],
              "stable_key_after_writes": trajectories["stable_prefix"][2]["cache_key"] == trajectories["stable_prefix"][6]["cache_key"],
              "stable_fixed_system": len({row["messages"][0].content for row in trajectories["stable_prefix"] if row["tools"]}) == 1}
    print(json.dumps({"offline_checks": checks}), flush=True)
    assert all(checks.values())
    if not live:
        (destination / "offline-projections.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        return
    transport = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="payload-only", use_responses_api=True)
    rows = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
        for index in range(len(trajectories["legacy"])):
            for strategy in ("legacy", "stable_prefix"):
                item = trajectories[strategy][index]
                payload = transport._get_request_payload(item["messages"],
                    **({"tools": item["tools"], "tool_choice": "none"} if item["tools"] else {}))
                payload.update(stream=True, reasoning={"effort": "low"}, max_output_tokens=4096 if item["phase"] == "compactor" else 64)
                if item["cache_key"]:
                    payload["prompt_cache_key"] = item["cache_key"]
                assert agent.RUNTIME_CONTEXT_MARKER not in json.dumps(payload)
                assert "prompt_cache_breakpoint" not in json.dumps(payload)
                print(json.dumps({"request": strategy, "phase": item["phase"]}), flush=True)
                started = time.monotonic()
                data, first_progress = None, None
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if not response.is_success:
                        raise RuntimeError(f"Gateway returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                            continue
                        event = json.loads(line[5:])
                        if event.get("delta") and first_progress is None:
                            first_progress = time.monotonic() - started
                        if event.get("type") in {"response.completed", "response.incomplete"}:
                            data = event.get("response")
                assert data is not None, "Stream omitted terminal response"
                usage = usage_from_message(SimpleNamespace(response_metadata={"usage": data.get("usage")}))
                assert usage is not None, "Gateway usage missing"
                if item["phase"] == "compactor":
                    text = "".join(str(content.get("text") or "") for output in data.get("output", [])
                                   for content in output.get("content", []) if content.get("type") == "output_text")
                    summary = agent._parse_runtime_summary(AIMessage(content=text), 1500)
                    for following in trajectories[strategy][index + 1:]:
                        for message in following["messages"][1:]:
                            if str(message.content).startswith("以下是较早工具循环的模型生成工作摘要。"):
                                message.content = message.content.split("\n", 1)[0] + "\n" + summary
                row = {"strategy": strategy, "phase": item["phase"], **usage.__dict__,
                    "seconds": round(time.monotonic() - started, 3),
                    "first_progress_seconds": round(first_progress, 3) if first_progress is not None else None,
                    "system_hash": agent._cache_fingerprint(item["messages"][0].content),
                    "tools_hash": agent._cache_fingerprint(item["tools"])}
                rows.append(row)
                print(json.dumps(row), flush=True)
                (destination / "gateway-progress.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    aggregate = {strategy: totals([row for row in rows if row["strategy"] == strategy]) for strategy in trajectories}
    legacy, stable = aggregate["legacy"], aggregate["stable_prefix"]
    checks.update(uncached_input_lower=stable["uncached_input_tokens"] < legacy["uncached_input_tokens"],
        input_growth_at_most_5_percent=stable["input_tokens"] <= legacy["input_tokens"] * 1.05,
        after_writes_cached=any(row["cache_read_tokens"] > 0 for row in rows
            if row["strategy"] == "stable_prefix" and row["phase"] == "after_writes"),
        after_compaction_cached=any(row["cache_read_tokens"] > 0 for row in rows
            if row["strategy"] == "stable_prefix" and row["phase"] == "after_compaction"))
    report = {"kind": "Synthetic v2 projections, optimization off/on, real compactor usage included",
              "aggregate": aggregate, "checks": checks, "rows": rows}
    (destination / "gateway-comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"aggregate": aggregate, "checks": checks}), flush=True)
    assert all(checks.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, default=DESTINATION)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    asyncio.run(main(args.live, args.output.resolve()))
