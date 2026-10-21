"""Compare configured providers using real, isolated source Agent tasks.

Requires --live to contact gateways. Only synthetic HTML in memory is edited;
no chat, document, model configuration or usage-accounting rows are written.
Artifacts contain numeric usage, tool names and fingerprints, never credentials
or provider error bodies. Cache fields omitted by a gateway remain unknown.
"""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import dataclasses
import hashlib
import json
import logging
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.base import Base
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.chat_session import ChatSession
from app.services import chat_agent as agent
from app.services.agent_context import AgentContextBuilder, ContextRecord
from app.services import model_call_accounting as accounting
from app.services.model_access import is_model_available
from app.services.source_agent import create_source_workspace

CURRENT = contextvars.ContextVar("cache_benchmark_observer", default=None)
DEFAULT_MODELS = [10, 40, 38, 22, 27, 32, 37]
SOURCE = '<section><h1>旧标题</h1><p id="target">正文原句。</p><p id="note">旧备注。</p>' + "".join(
    f'<p id="item-{i}">合成测试段落{i}：仅用于缓存验收，其余源码必须完整保留。</p>' for i in range(80)
) + "</section>"
REQUEST = (
    "请执行合成稿验收：先 list_files 列目录，再 read_file 读取 /article.html，"
    "然后 search_files 搜索旧标题。仅做以下三处修改，每处单独写入，不得合并："
    "1. 旧标题改为新标题；2. 正文原句。改为正文新句。；3. 旧备注。改为新备注。。"
    "每次写入后 read_file 重新读取当前源码和最新 revision，再进行下一次写入。"
    "最后核对三处修改且其他源码逐字不变。使用核心工具，不加载额外工具组，"
    "不调用外部工具，不询问用户。完成后简短报告。"
)
FOLLOWUP = (
    "上一轮已完成。这是新要求：先 read_file 读取当前源码和最新 revision，"
    "仅将新备注。改为第二轮备注。，写入后再次 read_file 核对。"
    "其余源码逐字保持，不加载额外工具组，不调用外部工具，不询问用户。简短报告。"
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:20]


def numeric_tree(value):
    """Retain counters only, dropping arbitrary strings from gateway metadata."""
    if isinstance(value, dict):
        return {str(k): result for k, v in value.items() if (result := numeric_tree(v)) is not None}
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def safe_error(exc):
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    category = "provider_or_protocol_error"
    for name, markers in (
        ("authentication", ("unauthorized", "invalid api key", "authentication", "401")),
        ("quota_or_rate_limit", ("quota", "rate limit", "余额", "额度", "429", "insufficient")),
        ("model_unavailable", ("model not found", "no available", "not exist", "无可用", "model_not_found")),
        ("unsupported_parameter", ("unsupported", "invalid parameter", "unknown parameter", "not supported")),
        ("timeout", ("timeout", "timed out", "未产生新输出")),
        ("connection", ("connect", "ssl", "certificate", "peer closed")),
    ):
        if any(marker in text for marker in markers):
            category = name
            break
    flags = [flag for flag, markers in (
        ("prompt_cache_key", ("prompt_cache_key",)),
        ("assistant_role", ("assistant",)),
        ("last_message", ("last message", "last_message", "final message")),
        ("prefix_mode", ("prefix",)),
        ("reasoning_content", ("reasoning_content",)),
        ("tool_protocol", ("tool_call", "function_call", "function call")),
        ("unknown_field", ("unknown field", "unrecognized", "unknown parameter", "extra inputs")),
    ) if any(marker in text for marker in markers)]
    body = getattr(exc, "body", None)
    details = body.get("error", body) if isinstance(body, dict) else {}
    codes = {key: value for key in ("code", "type", "param")
             if isinstance(details, dict) and isinstance(value := details.get(key), str)
             and re.fullmatch(r"[A-Za-z0-9_.\[\]-]{1,80}", value)}
    return {"type": type(exc).__name__, "status": status if isinstance(status, int) else None,
            "category": category, "diagnostic_flags": flags, "provider_codes": codes}


def aggregate(rows):
    reported = [r for r in rows if r.get("usage_reported")]
    known = [r for r in reported if r.get("cache_read_reported")]
    inputs = sum(r["input_tokens"] for r in reported)
    known_inputs = sum(r["input_tokens"] for r in known)
    reads = sum(r["cache_read_tokens"] for r in known)
    return {
        "calls": len(rows), "usage_reported_calls": len(reported), "cache_read_reported_calls": len(known),
        "input_tokens": inputs, "output_tokens": sum(r["output_tokens"] for r in reported),
        "cache_read_tokens": reads if known else None,
        "cache_write_tokens": sum(r["cache_write_tokens"] for r in reported
                                  if r.get("cache_write_reported"))
                              if any(r.get("cache_write_reported") for r in reported) else None,
        "cache_known_input_tokens": known_inputs,
        "uncached_input_tokens": known_inputs - reads if known else None,
        "weighted_hit_rate": reads / known_inputs if known_inputs else None,
        "max_cache_read_tokens": max((r["cache_read_tokens"] for r in known), default=None),
        "request_seconds": round(sum(r.get("seconds", 0) for r in rows), 3),
        "median_first_output_seconds": statistics.median(
            values) if (values := [r["first_seconds"] for r in rows if r.get("first_seconds") is not None]) else None,
    }


class Observer:
    def __init__(self, info, destination, max_calls):
        self.info, self.destination, self.max_calls = info, destination, max_calls
        self.rows, self.events, self.tasks = [], [], []
        self.task_index, self.session = 0, None
        self.started = time.monotonic()

    def save(self):
        result = {"model": self.info, "rows": self.rows, "events": self.events, "tasks": self.tasks,
                  "aggregate": aggregate(self.rows),
                  "by_task": {str(i): aggregate([r for r in self.rows if r["task"] == i]) for i in (0, 1)},
                  "elapsed_seconds": round(time.monotonic() - self.started, 3)}
        path = self.destination / f'model-{self.info["model_id"]}.json'
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return result

    def start(self, messages, kwargs, phase):
        if len(self.rows) >= self.max_calls:
            raise RuntimeError("Synthetic benchmark call limit reached")
        row = {"call": len(self.rows), "task": self.task_index, "phase": phase,
               "usage_reported": False, "cache_read_reported": False, "cache_write_reported": False,
               "system_hash": fingerprint(messages[0].content) if messages else None,
               "schema_hash": fingerprint(kwargs.get("tools") or []), "messages": len(messages),
               "runtime_state_count": sum(agent._is_runtime_context(m) for m in messages),
               "revision": self.session.source_file().revision if self.session else None,
               "tools": [], "first_seconds": None}
        self.rows.append(row)
        self.save()
        print(json.dumps({"model": self.info["model_id"], "started_call": row["call"],
                          "task": self.task_index, "phase": phase}), flush=True)
        return row, time.monotonic()

    def finish(self, row, started, message, messages, error=None, llm_output=None):
        usage = accounting.usage_from_message(message)
        if usage is None and llm_output:
            usage = accounting.usage_from_message(SimpleNamespace(response_metadata=llm_output))
        candidates = accounting._usage_candidates(message)
        if llm_output:
            candidates.extend(accounting._usage_candidates(SimpleNamespace(response_metadata=llm_output)))
        row.update(seconds=round(time.monotonic() - started, 3), usage_reported=usage is not None,
                   cache_read_reported=any(accounting._cache_tokens(c, write=False) is not None for c in candidates),
                   cache_write_reported=any(accounting._cache_tokens(c, write=True) is not None for c in candidates),
                   usage_counters=[numeric_tree(dict(c)) for c in candidates])
        if usage is not None:
            row.update(dataclasses.asdict(usage))
        if isinstance(error, GeneratorExit):
            row["stream_closed_early"] = True
        elif error is not None:
            row["error"] = safe_error(error)
        if message is not None:
            converted = agent.message_chunk_to_message(message)
            row["tools"] = [x.get("name") for x in getattr(converted, "tool_calls", [])]
        self.save()
        print(json.dumps({"model": self.info["model_id"], **{k: v for k, v in row.items()
            if k not in {"usage_counters", "system_hash", "schema_hash", "revision"}}}), flush=True)


def install_observers():
    """Instrument only this process; preserve native model and graph behavior."""
    originals = []
    for cls in (agent.OpenAICompatibleChatModel, agent.ChatAnthropic, agent.GeminiNativeChatModel):
        original_stream = cls._astream
        original_generate = cls._agenerate

        def make_stream(original):
            async def monitored(self, messages, *args, **kwargs):
                observer = CURRENT.get()
                if observer is None:
                    async for generation in original(self, messages, *args, **kwargs):
                        yield generation
                    return
                row, started = observer.start(messages, kwargs, "agent")
                combined, error = None, None
                try:
                    async for generation in original(self, messages, *args, **kwargs):
                        chunk = generation.message
                        if row["first_seconds"] is None and (
                            agent._model_chunk_has_text_progress(chunk) or chunk.tool_call_chunks
                        ):
                            row["first_seconds"] = round(time.monotonic() - started, 3)
                        combined = chunk if combined is None else combined + chunk
                        yield generation
                except BaseException as exc:
                    error = exc
                    raise
                finally:
                    observer.finish(row, started, combined, messages, error)
            return monitored

        def make_generate(original):
            async def monitored(self, messages, *args, **kwargs):
                observer = CURRENT.get()
                if observer is None:
                    return await original(self, messages, *args, **kwargs)
                row, started = observer.start(messages, kwargs, "compactor")
                response, error = None, None
                try:
                    response = await original(self, messages, *args, **kwargs)
                    return response
                except BaseException as exc:
                    error = exc
                    raise
                finally:
                    observer.finish(row, started, response.generations[0].message if response and response.generations else None,
                                    messages, error, response.llm_output if response else None)
            return monitored

        originals.extend([(cls, "_astream", original_stream), (cls, "_agenerate", original_generate)])
        cls._astream = make_stream(original_stream)
        cls._agenerate = make_generate(original_generate)
    return originals


def load_configs(ids, live, cache_override="configured"):
    configs = []
    with SessionLocal() as db:
        for model_id in ids:
            model = db.get(AIModel, model_id)
            if model is None:
                raise ValueError(f"Unknown model id {model_id}")
            provider = model.provider
            configured_cache = model.prompt_cache_enabled
            # Never mutate an ORM object, even temporarily: a subsequent query
            # could autoflush it. Override only a detached plain config copy.
            if cache_override != "configured":
                model = SimpleNamespace(**{column.name: getattr(model, column.name)
                                           for column in AIModel.__table__.columns}, provider=provider)
                model.prompt_cache_enabled = cache_override == "enabled"
            info = {"model_id": model.id, "model": model.model_name, "provider_id": provider.id,
                    "provider": provider.name, "host": urlsplit(provider.base_url).hostname,
                    "protocol": provider.provider_type.value, "available": is_model_available(model),
                    "cache_enabled": model.prompt_cache_enabled,
                    "configured_cache_enabled": configured_cache, "cache_override": cache_override,
                    "thinking_mode": "enabled", "thinking_effort": model.default_thinking_effort,
                    "max_output_tokens": min(model.max_output_tokens, 16384),
                    "tool_result_max_tokens": model.tool_result_max_tokens,
                    "input_budget_tokens": model.context_compaction_threshold_tokens}
            key = agent.build_agent_prompt_cache_key(provider, model, 1) if model.prompt_cache_enabled else None
            chat = compactor = None
            if live and info["available"]:
                chat, _ = agent.build_chat_model(provider, model, "enabled", "auto", prompt_cache_key=key,
                    max_completion_tokens=info["max_output_tokens"], request_timeout_seconds=180)
                compactor = agent.build_compaction_model(provider, model)
            replay_config = SimpleNamespace(**{column.name: getattr(model, column.name)
                                              for column in AIModel.__table__.columns}, provider=provider)
            configs.append((info, chat, compactor, key, replay_config))
    return configs


async def run_config(config, destination, timeout, max_calls):
    info, chat, compactor, key, replay_config = config
    observer = Observer(info, destination, max_calls)
    if not info["available"]:
        observer.tasks.append({"task": 0, "status": "skipped_unavailable"})
        return observer.save()
    token = CURRENT.set(observer)
    observer.session = session = agent.HtmlEditSession(SOURCE, tool_result_max_tokens=info["tool_result_max_tokens"])
    records = []
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    replay_db = Session(engine)
    replay_session = ChatSession(document_id=1, title="isolated cache benchmark")
    replay_db.add(replay_session)
    replay_db.flush()
    expected = SOURCE.replace("旧标题", "新标题").replace("正文原句。", "正文新句。").replace("旧备注。", "新备注。")
    try:
        async with asyncio.timeout(timeout):
            for task_index, request in enumerate((REQUEST, FOLLOWUP)):
                observer.task_index = task_index
                if task_index:
                    expected = expected.replace("新备注。", "第二轮备注。")
                final = None
                errors, tool_errors, writes = [], 0, 0
                # Reconstruct each task through the real preflight builder,
                # including event replay, revision handling and token budgets.
                factory = agent.runtime_context_budget_factory(replay_config, "多供应商缓存合成验收",
                    session.html, tool_protocol="v2")
                builder = AgentContextBuilder(replay_db, 1, replay_session.id, replay_config,
                    create_source_workspace(session), [], "", current_request=request,
                    runtime_context_factory=factory,
                    tool_schema_tokens=agent.editor_tool_schema_tokens(info["protocol"], tool_protocol="v2"))
                builder.records = builder._source_record_cache = records
                prepared = await builder.prepare(compactor)
                starting_revision = session.source_file().revision
                async for event in agent.run_agent_loop(
                    chat, "多供应商缓存合成验收", session.html, request,
                    prepared.workspace_map, prepared.memory, prepared.history, session=session,
                    provider_type=info["protocol"], prompt_cache_enabled=info["cache_enabled"],
                    prompt_cache_key=key, tool_protocol="v2", compaction_model=compactor,
                    run_input_budget_tokens=prepared.stats["active_context_threshold_tokens"],
                    trace_id=f'cache-multiprovider-{destination.name}-m{info["model_id"]}-t{task_index}',
                ):
                    kind, data = event.get("event"), event.get("data") or {}
                    if kind == "error":
                        errors.append(safe_error(RuntimeError(str(data.get("message") or ""))))
                    if kind == "tool_result":
                        activity = data.get("activity") or {}
                        tool_errors += int(activity.get("kind") == "error")
                        writes += int(data.get("name") in {"edit_file", "apply_patch", "write_file"}
                                      and activity.get("kind") != "error")
                        observer.events.append({"task": task_index, "event": kind,
                            "tool": data.get("name"), "kind": activity.get("kind"),
                            "revision": session.source_file().revision})
                    if kind == "model_turn_retry":
                        observer.events.append({"task": task_index, "event": kind, "attempt": data.get("attempt")})
                    if kind == "context_stats" and data.get("state") == "in_run_compacted":
                        observer.events.append({"task": task_index, "event": "compaction"})
                    if kind == "user_question":
                        errors.append({"category": "unexpected_user_question"})
                    if kind == "final":
                        final = event
                observer.tasks.append({"task": task_index, "status": "completed" if final else "failed",
                    "exact_source_edits": session.html == expected, "errors": errors,
                    "tool_errors": tool_errors, "writes": writes,
                    "source_hash": fingerprint(session.html)})
                observer.save()
                if final is None or session.html != expected:
                    break
                records.append(ContextRecord(len(records) + 1, task_index * 2 + 1, "user", {"content": request},
                                             document_revision=starting_revision))
                for item in final["data"]["context_events"]:
                    # JSON round trip matches persisted event payload semantics;
                    # never reuse transport projections/cache hints as history.
                    item = json.loads(json.dumps(item, ensure_ascii=False))
                    records.append(ContextRecord(len(records) + 1, task_index * 2 + 2, item["kind"], item["payload"],
                                                 document_revision=str(item.get("document_revision") or "")))
    except Exception as exc:
        observer.tasks.append({"task": observer.task_index, "status": "aborted", "error": safe_error(exc)})
    finally:
        CURRENT.reset(token)
        replay_db.close()
        engine.dispose()
    return observer.save()


def write_report(destination, results):
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Local configured gateways; actual production v2 graph; synthetic memory-only edits",
        "settings_changed": False, "seeded_history": False, "history_replay": "production AgentContextBuilder + JSON ledger events",
        "cache_rate_denominator": "Only gateway input usage with an explicit cache-read counter; missing is unknown",
        "results": results}
    (destination / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 多供应商真实 Agent 缓存实测", "", report["created_at"], "",
        "本地数据库当前配置、真实 v2 Agent 工具执行、内存合成稿。未修改模型配置或业务记录。",
        "每个模型先独立读取/搜索并连续单独修改三处，再追加一轮新要求。无伪造历史。",
        "保留各模型默认思考强度，单次输出上限 16,384；每条路由有时间及调用数上限。",
        "如 model.cache_override 不是 configured，开关覆盖仅存在于本次测试客户端，不更新数据库。", "",
        "命中率按网关实报输入 token 加权；缺缓存字段显示未知，不能作为零命中。",
        "各模型自行决定工具轨迹，跨模型结果用于诊断，不代表价格或性能排名。", "",
        "|供应商 / 模型|缓存优化开关|调用 / 用量 / 缓存字段覆盖|输入 token|读取缓存 token|加权命中|首个有效输出中位数|请求累计秒|两轮编辑|",
        "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for result in results:
        i, a = result["model"], result["aggregate"]
        rate = f'{a["weighted_hit_rate"]:.2%}' if a["weighted_hit_rate"] is not None else "未知"
        first = f'{a["median_first_output_seconds"]:.2f}s' if a["median_first_output_seconds"] is not None else "—"
        inputs = str(a["input_tokens"]) if a["usage_reported_calls"] else "未知"
        correct = sum(t.get("status") == "completed" and t.get("exact_source_edits") for t in result["tasks"])
        lines.append(f'|{i["provider"]} / {i["model"]}|{"开" if i["cache_enabled"] else "关"}|'
            f'{a["calls"]} / {a["usage_reported_calls"]} / {a["cache_read_reported_calls"]}|'
            f'{inputs}|{a["cache_read_tokens"] if a["cache_read_tokens"] is not None else "未知"}|'
            f'{rate}|{first}|{a["request_seconds"]:.1f}|{correct}/2|')
    lines.extend(["", "逐调用证据和分轮汇总见 comparison.json 及 model-<id>.json。",
        "未主动触发压缩；若自然触发，压缩模型调用也纳入消耗。首请求不保证网关缓存为空。",
        "这是本机配置直连网关的结果，未连接部署服务器，也未验证其代码版本和运行配置。"])
    (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main(options):
    configs = load_configs(options.models, options.live, options.cache_override)
    if not options.live:
        print(json.dumps([c[0] for c in configs], ensure_ascii=False, indent=2))
        return
    destination = Path(options.output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    originals = install_observers()
    semaphore = asyncio.Semaphore(options.concurrency)
    results = []

    async def bounded(config):
        async with semaphore:
            result = await run_config(config, destination, options.timeout, options.max_calls)
            results.append(result)
            write_report(destination, sorted(results, key=lambda r: options.models.index(r["model"]["model_id"])))
            print(json.dumps({"finished_model": result["model"], "aggregate": result["aggregate"],
                              "tasks": result["tasks"]}, ensure_ascii=False), flush=True)

    try:
        await asyncio.gather(*(bounded(c) for c in configs))
    finally:
        for cls, name, original in originals:
            setattr(cls, name, original)
    print(json.dumps({"report": str(destination / "report.md")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--models", type=int, nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--output", default="../outputs/multi-provider-agent-cache-20261017")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900, help="Wall seconds per provider, including both tasks")
    parser.add_argument("--max-calls", type=int, default=24)
    parser.add_argument("--cache-override", choices=("configured", "enabled", "disabled"), default="configured")
    logging.disable(logging.CRITICAL)
    asyncio.run(main(parser.parse_args()))
