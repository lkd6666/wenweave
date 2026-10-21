"""Isolated gateway boundary probes and actual in-memory source Agent runs.

Only synthetic source is edited. Reports contain usage, hashes and tool names,
never credentials or source text. The runtime role override is an experiment,
not a model configuration change.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

import app.models  # noqa: F401
from app.core.crypto import decrypt_secret
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.ai_provider import ProviderType
from app.models.agent_run import AgentRun, AgentRunStatus
from app.services import chat_agent as agent
from app.services.model_call_accounting import usage_from_message
from app.services.openai_compatible_chat_model import OpenAICompatibleChatModel
from app.services.source_agent import create_source_workspace
from scripts.benchmark_source_prompt_cache import capture, totals

DESTINATION = Path(__file__).resolve().parents[2] / "outputs/source-cache-comprehensive-20261013"


def save(name, value):
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def config():
    with SessionLocal() as db:
        active = db.query(AgentRun).filter(AgentRun.status.in_(
            [AgentRunStatus.RUNNING, AgentRunStatus.PENDING, AgentRunStatus.CANCELLING])).count()
        assert active == 0, "A business Agent is active; avoid interfering with its gateway route"
        model = db.get(AIModel, 40)
        assert model and model.is_enabled and model.prompt_cache_enabled
        assert model.model_name == "gpt-6.1-sol"
        assert model.provider.provider_type == ProviderType.OPENAI_RESPONSES
        assert urlsplit(model.provider.base_url).hostname in {"naiccc.com", "api.naiccc.com"}
        # Build all clients inside the transaction without retaining encrypted secrets in artifacts.
        key = agent.build_agent_prompt_cache_key(model.provider, model, 1)
        live, _ = agent.build_chat_model(model.provider, model, "enabled", "xhigh",
            max_completion_tokens=8192, request_timeout_seconds=180, prompt_cache_key=key)
        compactor = agent.build_compaction_model(model.provider, model)
        return live, compactor, key, model.provider.base_url.rstrip("/") + "/responses", {
            "Authorization": "Bearer " + decrypt_secret(model.provider.api_key_encrypted)}


def role_projection(messages, role):
    projected = []
    for index, message in enumerate(messages):
        if role == "user" and agent._is_runtime_context(message):
            # Remove the internal marker to reproduce the pre-fix wire path.
            message = HumanMessage(content=message.content)
        elif role in {"assistant", "anchored"} and agent._is_runtime_context(message):
            message = AIMessage(content=message.content)
        elif role == "developer" and agent._is_runtime_context(message):
            message = SystemMessage(content=message.content, additional_kwargs={"__openai_role__": "developer"})
        projected.append(message)
        if role == "anchored" and isinstance(message, ToolMessage) and (
                index + 1 == len(messages) or not isinstance(messages[index + 1], ToolMessage)):
            projected.append(HumanMessage(content="【服务端工具结果边界：继续既有用户任务】"))
    return projected


async def boundaries(anchors=False):
    _, _, key, url, headers = config()
    captured = await capture(True, key)
    tools = captured[0]["tools"]
    transport = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="payload-only", use_responses_api=True)
    nonce = uuid.uuid4().hex[:12]
    rows = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), trust_env=False) as client:
        variants = ("assistant", "anchored") if anchors else ("user", "assistant", "developer")
        for role in variants:
            fixed = SystemMessage(content="Synthetic cache diagnostic cohort " + nonce + ":" + role + "\n" + captured[0]["messages"][0].content)
            history = [HumanMessage(content="合成历史资料，已完成读取。")]
            for index in range(12):
                cid = f"history-{index}"
                history.extend([AIMessage(content="", tool_calls=[{"id": cid, "name": "read_file", "args": {"path": "/article.html"}}]),
                    ToolMessage(content=json.dumps({"content": "合成历史段落，日期与编号无业务含义。" * 140,
                        "revision": str(index)}, ensure_ascii=False), tool_call_id=cid, name="read_file")])
            history.append(HumanMessage(content="继续只读核对资料。只回答 OK，不调用工具。"))
            state = captured[0]["messages"][-1]
            for phase in ("seed", "identical", "read_growth", "revision_growth"):
                if phase in {"read_growth", "revision_growth"}:
                    cid = "new-" + phase
                    history.extend([AIMessage(content="", tool_calls=[{"id": cid, "name": "read_file", "args": {"path": "/article.html"}}]),
                        ToolMessage(content=json.dumps({"content": "新的合成只读结果。" * 160, "revision": phase}, ensure_ascii=False),
                            tool_call_id=cid, name="read_file")])
                if phase == "revision_growth":
                    state = captured[4]["messages"][-1]
                payload = transport._get_request_payload(role_projection([fixed, *history, state], role),
                    tools=tools, tool_choice="none")
                payload.update(stream=True, reasoning={"effort": "low"}, max_output_tokens=128,
                    prompt_cache_key=f"yb-cache-probe-{nonce}-{role}")
                assert agent.RUNTIME_CONTEXT_MARKER not in json.dumps(payload)
                assert "prompt_cache_breakpoint" not in json.dumps(payload)
                print(json.dumps({"request": role, "phase": phase}), flush=True)
                started = time.monotonic()
                data, first = None, None
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if not response.is_success:
                        raise RuntimeError(f"Gateway HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                            continue
                        event = json.loads(line[5:])
                        if event.get("delta") and first is None:
                            first = time.monotonic() - started
                        if event.get("type") in {"response.completed", "response.incomplete"}:
                            data = event.get("response")
                assert data, "Missing terminal response"
                usage = usage_from_message(SimpleNamespace(response_metadata={"usage": data.get("usage")}))
                assert usage is not None
                row = {"strategy": role, "phase": phase, **dataclasses.asdict(usage),
                    "seconds": round(time.monotonic() - started, 3), "first_seconds": first,
                    "input_hash": agent._cache_fingerprint(payload["input"]),
                    "state_role": payload["input"][-1].get("role")}
                rows.append(row)
                save("boundary-anchors.json" if anchors else "boundary-probes.json", {
                    "rows": rows, "aggregate": {r: totals([x for x in rows if x["strategy"] == r]) for r in variants}})
                print(json.dumps(row), flush=True)


async def comparison(suffix):
    """Replay equal long trajectories, including actual summary consumption."""
    _, _, key, url, headers = config()
    nonce = uuid.uuid4().hex[:12]
    trajectories = {"legacy": await capture(False, key), "user_tail": await capture(True, key),
                    "optimized": await capture(True, key)}
    historical = [HumanMessage(content="以下合成历史只用于缓存验收，之前的只读任务已经完成。")]
    for i in range(24):
        cid = f"cohort-read-{i}"
        historical.extend([AIMessage(content="", tool_calls=[{"id": cid, "name": "read_file", "args": {"path": "/article.html"}}]),
            ToolMessage(content=json.dumps({"revision": "past", "content": f"合成历史段落{i}，" + "已读资料仅供回顾，定位必须重新读取当前文件。" * 45},
                ensure_ascii=False), tool_call_id=cid, name="read_file")])
    historical.append(AIMessage(content="前一轮已完成。"))
    transport = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="payload-only", use_responses_api=True)
    rows = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), trust_env=False) as client:
        for index in range(len(trajectories["legacy"])):
            for strategy, items in trajectories.items():
                item = items[index]
                messages = item["messages"]
                if index < 7:
                    messages = [messages[0], *historical, *messages[1:]]
                messages = [SystemMessage(content=f"Synthetic equal trajectory {nonce}:{strategy}\n" + messages[0].content), *messages[1:]]
                payload = transport._get_request_payload(role_projection(messages, "user" if strategy == "user_tail" else "native"),
                    **({"tools": item["tools"], "tool_choice": "none"} if item["tools"] else {}))
                payload.update(stream=True, reasoning={"effort": "low"},
                    max_output_tokens=4096 if item["phase"] == "compactor" else 128)
                if item["cache_key"]:
                    payload["prompt_cache_key"] = f"yb-equal-trajectory-{nonce}-{strategy}-" + item["cache_key"].split("-src2-")[-1]
                assert agent.RUNTIME_CONTEXT_MARKER not in json.dumps(payload)
                assert "prompt_cache_breakpoint" not in json.dumps(payload)
                print(json.dumps({"request": strategy, "phase": item["phase"]}), flush=True)
                started, first, data = time.monotonic(), None, None
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if not response.is_success:
                        raise RuntimeError(f"Gateway HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                            continue
                        event = json.loads(line[5:])
                        if event.get("delta") and first is None:
                            first = time.monotonic() - started
                        if event.get("type") in {"response.completed", "response.incomplete"}:
                            data = event.get("response")
                assert data, "Missing terminal response"
                usage = usage_from_message(SimpleNamespace(response_metadata={"usage": data.get("usage")}))
                assert usage is not None
                if item["phase"] == "compactor":
                    text = "".join(str(content.get("text") or "") for output in data.get("output", [])
                        for content in output.get("content", []) if content.get("type") == "output_text")
                    summary = agent._parse_runtime_summary(AIMessage(content=text), 1500)
                    for following in items[index + 1:]:
                        for message in following["messages"][1:]:
                            if str(message.content).startswith("以下是较早工具循环的模型生成工作摘要。"):
                                message.content = message.content.split("\n", 1)[0] + "\n" + summary
                row = {"strategy": strategy, "phase": item["phase"], **dataclasses.asdict(usage),
                    "seconds": round(time.monotonic() - started, 3), "first_seconds": first,
                    "system_hash": agent._cache_fingerprint(messages[0].content),
                    "schema_hash": agent._cache_fingerprint(payload.get("tools"))}
                rows.append(row)
                save(f"trajectory-{suffix}-progress.json", rows)
                print(json.dumps(row), flush=True)
    aggregate = {strategy: totals([row for row in rows if row["strategy"] == strategy]) for strategy in trajectories}
    previous, improved = aggregate["user_tail"], aggregate["optimized"]
    checks = {"uncached_input_lower": improved["uncached_input_tokens"] < previous["uncached_input_tokens"],
        "input_growth_at_most_5_percent": improved["input_tokens"] <= previous["input_tokens"] * 1.05,
        "same_call_and_compaction_counts": len({x["calls"] for x in aggregate.values()}) == 1,
        "real_compactor_usage_included": all(any(x["phase"] == "compactor" and x["input_tokens"] > 0
            for x in rows if x["strategy"] == strategy) for strategy in trajectories)}
    report = {"kind": "Equal synthetic graph trajectories with 24 earlier tool boundaries and real compactor calls",
              "aggregate": aggregate, "checks": checks, "rows": rows}
    save(f"trajectory-{suffix}-comparison.json", report)
    print(json.dumps({"aggregate": aggregate, "checks": checks}), flush=True)
    assert all(checks.values())


async def actual(role, suffix):
    live, compactor, key, _, _ = config()
    rows = []
    latest_history = []
    task_index = 0
    original = OpenAICompatibleChatModel._astream

    async def monitored(self, messages, *args, **kwargs):
        nonlocal latest_history
        projected = role_projection(messages, role)
        started, first, aggregate = time.monotonic(), None, None
        payload = self._get_request_payload(projected, **kwargs)
        names = []
        error = None
        try:
            async for generation in original(self, projected, *args, **kwargs):
                chunk = generation.message
                if first is None and (chunk.content or chunk.tool_call_chunks or chunk.additional_kwargs):
                    first = time.monotonic() - started
                aggregate = chunk if aggregate is None else aggregate + chunk
                names.extend(x["name"] for x in chunk.tool_call_chunks if x.get("name"))
                yield generation
        except Exception as exc:
            error = {"type": type(exc).__name__, "status": getattr(exc, "status_code", None),
                     "detail": str(exc)[:700]}
            raise
        finally:
            usage = usage_from_message(aggregate)
            if aggregate is not None:
                latest_history = [*agent._without_runtime_context(messages)[1:],
                                  agent.message_chunk_to_message(aggregate)]
            row = {"turn": len(rows), "task": task_index, "strategy": role, "usage_reported": usage is not None,
                **(dataclasses.asdict(usage) if usage is not None else {}),
                "seconds": round(time.monotonic() - started, 3), "first_seconds": first,
                "tools": names, "system_hash": agent._cache_fingerprint(projected[0].content),
                "state_role": payload["input"][-1].get("role"),
                "schema_hash": agent._cache_fingerprint(payload.get("tools")),
                "messages": len(messages)}
            if error:
                row["error"] = error
            rows.append(row)
            save(f"actual-{suffix}.json", {"rows": rows})
            print(json.dumps(row), flush=True)

    OpenAICompatibleChatModel._astream = monitored
    source = '<section><h1>旧标题</h1><p id="target">正文原句。</p><p id="note">旧备注。</p>' + "".join(
        f'<p id="item-{i}">合成测试段落{i}：仅为验证缓存，其他内容应完整保留。</p>' for i in range(80)) + "</section>"
    session = agent.HtmlEditSession(source)
    history = [HumanMessage(content="前一轮已经读取了合成稿，已完成，接下来等待用户的新任务。")]
    for i in range(12):
        cid = f"prior-{i}"
        history.extend([AIMessage(content="", tool_calls=[{"id": cid, "name": "read_file", "args": {"path": "/article.html"}}]),
            ToolMessage(content=json.dumps({"path": "/article.html", "revision": "prior",
                "content": "较早合成只读资料，当前定位必须重新读取。" * 160}, ensure_ascii=False), tool_call_id=cid, name="read_file")])
    history.append(AIMessage(content="前一轮只读任务已完成。"))
    request = "请执行这个合成验收任务：先 list_files，再 read_file 读取当前源码，然后 search_file 搜索旧标题。仅把旧标题改为新标题；写入成功后重新读取最新 revision，再把正文原句。改为正文新句。；再读取最新 revision，然后把旧备注。改为新备注。。每个修改分别执行，使用最新 revision，不要合并三个写入。最后重新读取核对三处修改和其余段落未变。期间加载 history 工具组一次，并读取 /history 的可用目录（没有历史就跳过历史读取）；不要调用外部工具，不要询问用户。完成后简短报告。"
    failures, compactions = [], 0
    final = None
    print(json.dumps({"actual_agent": suffix, "state_role": role, "reasoning": "xhigh"}), flush=True)
    try:
        async for event in agent.run_agent_loop(live, "缓存合成验收", source, request,
                create_source_workspace(session).map_payload(), None, history, session=session,
                tool_protocol="v2", provider_type="openai_responses", prompt_cache_enabled=True,
                prompt_cache_key=key, run_input_budget_tokens=258000, compaction_model=compactor,
                trace_id="cache-acceptance-comprehensive-" + suffix):
            kind, data = event.get("event"), event.get("data") or {}
            if kind in {"tool_start", "tool_end", "error", "final", "user_question"}:
                print(json.dumps({"event": kind, "name": data.get("name") or data.get("tool_name"),
                    "status": data.get("status")}), flush=True)
            if kind == "error":
                failures.append("agent_error")
            if kind == "context_stats" and data.get("state") == "in_run_compacted":
                compactions += 1
            if kind == "final":
                final = event
        expected = source.replace("旧标题", "新标题").replace("正文原句。", "正文新句。").replace("旧备注。", "新备注。")
        first_correct = final is not None and session.html == expected
        if role == "native" and first_correct:
            task_index = 1
            final = None
            async for event in agent.run_agent_loop(live, "缓存合成验收", session.html,
                    "上一轮已完成。新的任务：先读取当前源码确认最新 revision，仅把新备注。改为第二轮备注。。写入后再读取核对，其余源码逐字保持，不要询问用户。",
                    create_source_workspace(session).map_payload(), None, latest_history, session=session,
                    tool_protocol="v2", loaded_tool_groups=["history"], provider_type="openai_responses",
                    prompt_cache_enabled=True, prompt_cache_key=key, run_input_budget_tokens=258000,
                    compaction_model=compactor, trace_id="cache-acceptance-comprehensive-followup-" + suffix):
                if event.get("event") == "error":
                    failures.append("followup_error")
                if event.get("event") == "final":
                    final = event
                if event.get("event") == "context_stats" and (event.get("data") or {}).get("state") == "in_run_compacted":
                    compactions += 1
            expected = expected.replace("新备注。", "第二轮备注。")
        reported = [x for x in rows if x.get("usage_reported")]
        report = {"kind": "Actual production graph and real XHigh model, in-memory synthetic edits only",
            "strategy": role, "rows": rows, "aggregate": totals(reported),
            "checks": {"final": final is not None, "exact_source_edits": session.html == expected,
                "first_task_correct": first_correct,
                "no_agent_errors": not failures, "all_usage_reported": len(rows) == len(reported)},
            "compactions": compactions, "source_hash": hashlib.sha256(session.html.encode()).hexdigest()}
        save(f"actual-{suffix}.json", report)
        print(json.dumps({"aggregate": report["aggregate"], "checks": report["checks"]}), flush=True)
        assert all(report["checks"].values()), "Actual Agent acceptance failed; see sanitized report"
    finally:
        OpenAICompatibleChatModel._astream = original


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("boundaries", "anchors", "comparison", "actual"))
    parser.add_argument("--role", default="native", choices=("native", "user", "assistant", "developer", "anchored"))
    parser.add_argument("--suffix", default="before")
    options = parser.parse_args()
    logging.disable(logging.CRITICAL)
    asyncio.run(boundaries(options.mode == "anchors") if options.mode in {"boundaries", "anchors"} else comparison(options.suffix) if options.mode == "comparison"
                else actual(options.role, options.suffix))
