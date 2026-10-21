"""Compare natural requests on both protocols without writing business data.

Run with --live --model-id ID for actual gateway measurements. Default uses a
scripted model and reports mechanism checks only. No credentials or prompts are
saved. Any attempted external tool is rejected before execution.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import ToolMessage
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.utils.function_calling import convert_to_openai_tool

import app.models  # noqa: F401
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.services import chat_agent as agent
from app.services.model_call_accounting import usage_from_message
from app.services.source_agent import create_source_workspace
from app.services.token_budget import estimate_tokens
from tests.test_agent_loop_end_to_end import ScriptedChatModel

DESTINATION = Path(__file__).resolve().parents[2] / "outputs/source-agent-20261012"
LOCAL_TOOLS = {"get_document_map", "search_html", "read_blocks", "apply_html_patch", "replace_document",
               "list_files", "read_file", "search_files", "edit_file", "apply_patch", "write_file",
               "update_task_plan", "read_wechat_compliance_spec", "check_compliance"}


def source_characters(message):
    """Count HTML/source fields, separately from JSON protocol metadata."""
    if message.name not in {'read_file', 'read_blocks', 'search_files', 'search_html', 'get_document_map'}:
        return 0
    try:
        payload = json.loads(message.content)
    except (TypeError, ValueError):
        return 0
    def count(value):
        if isinstance(value, list):
            return sum(count(item) for item in value)
        if isinstance(value, dict):
            return sum(len(item) if key in {'content', 'html', 'html_fragment'} and isinstance(item, str)
                       else count(item) for key, item in value.items())
        return 0
    return count(payload)


class RecordingBinding:
    def __init__(self, binding, tools, rows):
        self.binding, self.tools, self.rows = binding, tools, rows

    async def astream(self, messages, **kwargs):
        started = time.perf_counter()
        row = {"input_tokens_estimate": estimate_tokens(json.dumps([
            {"role": message.type, "content": message.content} for message in messages], ensure_ascii=False))
            + estimate_tokens(json.dumps([convert_to_openai_tool(tool) for tool in self.tools], ensure_ascii=False)),
            "tool_history_transmission_characters": sum(len(str(message.content)) for message in messages
                                                       if isinstance(message, ToolMessage)),
            "source_result_characters": sum(source_characters(message) for message in messages
                                             if isinstance(message, ToolMessage)), "provider_usage": None}
        self.rows.append(row)
        combined = None
        try:
            async for chunk in self.binding.astream(messages, **kwargs):
                combined = chunk if combined is None else combined + chunk
                if usage := usage_from_message(chunk):
                    row["provider_usage"] = usage.__dict__
                for call in chunk.tool_call_chunks:
                    if call.get("name") and call["name"] not in LOCAL_TOOLS:
                        raise RuntimeError("Benchmark rejected an external/nonlocal tool")
                yield chunk
        finally:
            row["seconds"] = round(time.perf_counter() - started, 3)
            if combined is not None:
                message = message_chunk_to_message(combined)
                row["output_tokens_estimate"] = estimate_tokens(json.dumps(
                    {"content": message.content, "tool_calls": message.tool_calls}, ensure_ascii=False))
                row["tool_calls"] = [call["name"] for call in message.tool_calls]
                if usage := usage_from_message(message):
                    row["provider_usage"] = usage.__dict__


def fixture(case):
    paragraphs = [f'<p style="text-indent:0;color:#333">第{i}段：保留中文🙂和原始文案。</p>' for i in range(1, 13)]
    source = '<section><h1>源码协议验收</h1>' + ''.join(paragraphs) + '</section>'
    selected = [{"selector": "section:nth-of-type(1) > p:nth-of-type(7)", "tag_name": "p",
                 "text": "第7段：保留中文🙂和原始文案。", "html": paragraphs[6]}] if case == "selection" else []
    request = ("把选中的段落首行缩进改成两个字符，保留其他内容和样式。" if selected else
               "把所有正文段落的首行缩进改成两个字符，保留其他内容和样式。")
    expected = source.replace(paragraphs[6], paragraphs[6].replace('text-indent:0', 'text-indent:2em')) if selected else source.replace('text-indent:0', 'text-indent:2em')
    return source, selected, request, expected


def scripted_model(session, case, protocol):
    if protocol == "v2":
        edits = [{"old_text": "text-indent:0", "new_text": "text-indent:2em", "replace_all": case == "bulk"}]
        if case == "selection":
            start = session.html.index('<p style="text-indent:0;color:#333">第7段')
            edits[0].update(start=start, end=session.html.index('</p>', start) + 4)
        script = [{"tool": ("edit_file", {"path": "/article.html", "revision": session.source_file().revision, "edits": edits})}]
    else:
        query = '第7段' if case == "selection" else '保留中文'
        matches = [item for item in session.search(query, limit=100)["results"] if item["tag"] == 'p']
        blocks = session.read_blocks([item['block_id'] for item in matches])["blocks"]
        script = [{"tool": ("search_html", {"query": query, "limit": 100})},
                  {"tool": ("read_blocks", {"block_ids": [item['block_id'] for item in blocks]})},
                  {"tool": ("apply_html_patch", {"revision": session.workspace().revision, "operations": [
                      {"block_id": item['block_id'], "expected_hash": item['expected_hash'], "mode": "replace_outer",
                       "html": item['html'].replace('text-indent:0', 'text-indent:2em')} for item in blocks]})}]
    return ScriptedChatModel(script=[*script, {"text": "已修改。"}], seen_messages=[], seen_message_counts=[])


async def measure(case, protocol, args):
    source, selected, request, expected = fixture(case)
    session = agent.HtmlEditSession(source)
    provider_type, cache_enabled, metadata = 'openai_responses', True, {}
    if args.live:
        with SessionLocal() as db:
            model = db.get(AIModel, args.model_id)
            if model is None or not model.is_enabled:
                raise RuntimeError("Benchmark model missing or disabled")
            provider_type, cache_enabled = model.provider.provider_type.value, bool(model.prompt_cache_enabled)
            metadata = {"model": model.model_name, "gateway_host": urlsplit(model.provider.base_url).hostname,
                        "thinking_effort": "low", "prompt_cache_enabled": cache_enabled}
            chat_model, _ = agent.build_chat_model(model.provider, model, thinking_mode="auto", thinking_effort="low",
                streaming=True, max_completion_tokens=4096, max_retries=0, request_timeout_seconds=90,
                prompt_cache_key=agent.build_agent_prompt_cache_key(model.provider, model, 0) if cache_enabled else None)
    else:
        chat_model = scripted_model(session, case, protocol)
    rows, events, preview = [], [], None
    original_bind = agent._bind_tools_with_prompt_cache
    def recording_bind(model, tools, **kwargs):
        return RecordingBinding(original_bind(model, tools, **kwargs), tools, rows)
    started = time.perf_counter()
    with patch.object(agent, '_bind_tools_with_prompt_cache', side_effect=recording_bind):
        async for event in agent.run_agent_loop(chat_model, "源码协议验收", source, request,
                create_source_workspace(session).map_payload() if protocol == 'v2' else session.document_map(),
                None, [], selected_elements=selected, session=session, tool_protocol=protocol,
                provider_type=provider_type, prompt_cache_enabled=cache_enabled):
            events.append(event)
            if preview is None and event['event'] == 'tool_result' and event['data'].get('html'):
                preview = round(time.perf_counter() - started, 3)
    tool_results = [event['data'] for event in events if event['event'] == 'tool_result']
    usage = [row['provider_usage'] for row in rows if row['provider_usage']]
    model_turns = sum(event['event'] == 'heartbeat' and event['data'].get('phase') == 'model_turn_started'
                      for event in events)
    result = {"case": case, "protocol": protocol, **metadata, "model_turns": model_turns,
              "model_requests": len(rows), "request_retries": max(0, len(rows) - model_turns),
              "source_tool_transmission_characters": sum(row['source_result_characters'] for row in rows),
              "tool_history_transmission_characters": sum(row['tool_history_transmission_characters'] for row in rows),
              "tool_result_characters": sum(len(str(item.get('model_input', {}).get('content', ''))) for item in tool_results),
              "first_preview_seconds": preview, "total_seconds": round(time.perf_counter() - started, 3),
              "provider_usage_complete": len(usage) == len(rows),
              "missing_usage_turns": len(rows) - len(usage),
              "estimated_input_tokens": sum(row['input_tokens_estimate'] for row in rows),
              "estimated_output_tokens": sum(row.get('output_tokens_estimate', 0) for row in rows),
              "reported_tokens_partial": {field: sum(item[field] for item in usage) for field in
                                   ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')},
              "exact_expected_source": session.html == expected, "final_received": events[-1]['event'] == 'final',
              "tool_calls": [call for row in rows for call in row.get('tool_calls', [])],
              "tool_errors": sum(item.get('status') == 'error' for item in tool_results), "turns": rows}
    print(json.dumps({key: value for key, value in result.items() if key != 'turns'}, ensure_ascii=False), flush=True)
    return result


async def main(args):
    DESTINATION.mkdir(parents=True, exist_ok=True)
    rows = []
    output = DESTINATION / ('live-comparison.json' if args.live else 'scripted-comparison.json')
    for index in range(args.runs):
        for case in ('selection', 'bulk'):
            for protocol in (('v1', 'v2') if index % 2 == 0 else ('v2', 'v1')):
                row = await measure(case, protocol, args)
                rows.append({"run": index + 1, **row})
                output.write_text(json.dumps({"kind": 'live natural requests' if args.live else 'scripted mechanism check',
                    "rows": rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    if not all(row['exact_expected_source'] and row['final_received'] and not row['tool_errors'] for row in rows):
        raise RuntimeError("Benchmark acceptance failed; inspect the saved report")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model-id', type=int, default=40)
    parser.add_argument('--runs', type=int, default=1)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    asyncio.run(main(args))
