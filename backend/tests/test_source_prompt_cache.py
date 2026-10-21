"""Prompt caching with source tools, lazy groups, compaction and recovery."""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.services import chat_agent as agent
from app.services.html_workspace import HtmlWorkspace
from app.services.openai_compatible_chat_model import (
    CACHE_BOUNDARY_TEXT, OpenAICompatibleChatModel, project_runtime_cache_messages,
)
from app.services.source_agent import create_source_workspace
from app.services.source_agent import source_selections
from tests.test_agent_loop_end_to_end import ScriptedChatModel
from tests.test_run_compaction import _assert_tool_pairing


class CaptureSourceModel(ScriptedChatModel):
    schemas: list[dict] = []
    cache_key: str | None = None
    schema_bind_count: int = 0
    seen_schemas: list[list[dict]] = []
    seen_cache_keys: list[str | None] = []

    def bind_tools(self, tools, **kwargs):
        self.schemas = [convert_to_openai_tool(item) for item in tools]
        self.cache_key = kwargs.get("prompt_cache_key")
        self.schema_bind_count += 1
        return super().bind_tools(tools, **kwargs)

    async def _astream(self, messages, **kwargs):
        self.seen_schemas.append(list(self.schemas))
        self.seen_cache_keys.append(self.cache_key)
        async for item in super()._astream(messages, **kwargs):
            yield item


def model(script):
    return CaptureSourceModel(script=script, seen_messages=[], seen_message_counts=[],
                              seen_schemas=[], seen_cache_keys=[])


def run(chat_model, session, **kwargs):
    options = {"prompt_cache_enabled": True, "provider_type": "openai_responses",
               "tool_protocol": "v2", "prompt_cache_key": "yb-agent-v1-p7-m40-s3", **kwargs}
    async def consume():
        return [event async for event in agent.run_agent_loop(
            chat_model, "源码缓存", session.html, "仅调整授权文字", create_source_workspace(session).map_payload(),
            None, [], session=session, **options)]
    return asyncio.run(consume())


def runtime_state(messages):
    content = messages[-1].content.removeprefix(agent._RUNTIME_CONTEXT_HEADER)
    return json.JSONDecoder().raw_decode(content.split("\n", 1)[1])[0]


class SourcePromptCacheTests(unittest.TestCase):
    def test_compaction_prices_only_retained_groups_and_keeps_parallel_outputs_together(self):
        from app.services.openai_compatible_chat_model import tool_result_group_count
        root = [SystemMessage(content="固定规则"), HumanMessage(content="当前真实请求")]
        cycles = []
        for index in range(8):
            cid = f"budget-{index}"
            cycles.extend([AIMessage(content="", tool_calls=[{"id": cid, "name": "read_file",
                "args": {"path": "/article.html"}}]), ToolMessage(content="历史资料 " * 1000,
                tool_call_id=cid, name="read_file")])
        messages = [*root, *cycles]
        per_group = 2000
        budget = sum(agent._provider_message_tokens(item, 1) for item in [*root, *cycles[-6:]]) + 3 * per_group + 1000
        compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
            field: "已完成历史读取" if field == "completed" else "" for field in agent._RUNTIME_SUMMARY_FIELDS}))))
        outgoing, stats = asyncio.run(agent.compact_run_messages_with_model(messages, budget, compactor,
            cache_boundary_tokens_per_group=per_group))
        self.assertEqual(tool_result_group_count(outgoing), 3)
        self.assertEqual(stats["used_tokens"], sum(agent._provider_message_tokens(item, 1) for item in outgoing) + 3 * per_group)
        self.assertLessEqual(stats["used_tokens"], budget)
        self.assertEqual(stats["original_tokens"], sum(agent._provider_message_tokens(item, 1) for item in messages) + 8 * per_group)
        compactor.ainvoke.assert_awaited_once()
        self.assertNotIn(CACHE_BOUNDARY_TEXT, str(compactor.ainvoke.call_args.args))
        _assert_tool_pairing(self, outgoing)
        # Structural recovery must also update the reserve after dropping cycles.
        structural, structural_stats = agent.compact_run_messages(messages, 5000,
            cache_boundary_tokens_per_group=per_group)
        self.assertEqual(structural_stats["used_tokens"], sum(agent._provider_message_tokens(item, 1)
            for item in structural) + tool_result_group_count(structural) * per_group)
        self.assertLessEqual(structural_stats["used_tokens"], 5000)
        _assert_tool_pairing(self, structural)

    def test_wire_state_is_data_and_history_prefix_survives_tools_and_revision_changes(self):
        session = agent.HtmlEditSession("<p>甲</p>")
        chat_model = model([
            {"tool": ("read_file", {"path": "/article.html"})},
            {"tool": ("edit_file", {"path": "/article.html", "revision": session.source_file().revision,
                                    "edits": [{"old_text": "甲", "new_text": "乙"}]})},
            {"text": "完成"},
        ])
        run(chat_model, session)
        for responses in (True, False):
            transport = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="unused",
                                                 use_responses_api=responses)
            payloads = [transport._get_request_payload(messages, tools=schemas)
                        for messages, schemas in zip(chat_model.seen_messages, chat_model.seen_schemas)]
            wire = [payload["input" if responses else "messages"] for payload in payloads]
            for messages, sent in zip(chat_model.seen_messages, wire):
                self.assertIsInstance(messages[-1], HumanMessage)
                self.assertTrue(agent._is_runtime_context(messages[-1]))
                self.assertFalse(agent._is_user_request(messages[-1]))
                self.assertEqual(sent[-1]["role"], "assistant")
                self.assertEqual(sum(item.get("role") == "user" and CACHE_BOUNDARY_TEXT not in json.dumps(item, ensure_ascii=False)
                                     for item in sent), 1)
                boundaries = sum(CACHE_BOUNDARY_TEXT in json.dumps(item, ensure_ascii=False) for item in sent)
                self.assertEqual(boundaries, sum(isinstance(item, ToolMessage) for item in messages))
                self.assertEqual(sum(agent._RUNTIME_CONTEXT_HEADER.strip() in json.dumps(item, ensure_ascii=False)
                                     for item in sent), 1)
                self.assertNotIn(agent.RUNTIME_CONTEXT_MARKER, json.dumps(sent))
                self.assertNotIn("prompt_cache_breakpoint", json.dumps(sent))
                _assert_tool_pairing(self, messages[:-1])
            self.assertEqual(wire[1][:len(wire[0]) - 1], wire[0][:-1])
            self.assertEqual(wire[2][:len(wire[1]) - 1], wire[1][:-1])
            self.assertNotEqual(wire[1][-1], wire[2][-1])
            self.assertEqual(runtime_state(chat_model.seen_messages[-1])["files"][0]["revision"],
                             session.source_file().revision)

    def test_parallel_results_get_one_wire_boundary_and_budget_counts_it_once(self):
        session = agent.HtmlEditSession("<p>正文</p>")
        live = model([{"tools": [("read_file", {"path": "/article.html"}),
                                   ("list_files", {})]}, {"text": "完成"}])
        events = run(live, session)
        internal = live.seen_messages[1]
        projected = project_runtime_cache_messages(internal)
        self.assertEqual(sum(item.content == CACHE_BOUNDARY_TEXT for item in projected), 1)
        self.assertFalse(any(item.content == CACHE_BOUNDARY_TEXT for item in internal))
        self.assertEqual(sum(agent._is_user_request(item) for item in internal), 1)
        _assert_tool_pairing(self, projected[:-1])
        stat = [item["data"] for item in events if item["event"] == "context_stats"
                and item["data"].get("state") == "request_context"][1]
        self.assertEqual(stat["used_tokens"], sum(agent._provider_message_tokens(item, 1) for item in projected))
        self.assertEqual(stat["breakdown"]["runtime_cache_boundaries"], agent.estimate_tokens(CACHE_BOUNDARY_TEXT))
        self.assertNotIn(CACHE_BOUNDARY_TEXT, json.dumps(events[-1]["data"]["context_events"], ensure_ascii=False))

    def test_ordinary_users_assistants_and_images_are_not_rewritten(self):
        request = HumanMessage(content=[{"type": "text", "text": "根据图片调整"},
            {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}])
        messages = [SystemMessage(content="规则"), request, AIMessage(content="前一轮已完成")]
        original = [item.model_dump() for item in messages]
        for responses in (True, False):
            transport = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="unused",
                                                 use_responses_api=responses)
            payload = transport._get_request_payload(messages)
            wire = payload["input" if responses else "messages"]
            self.assertEqual([item["role"] for item in wire], ["system", "user", "assistant"])
            self.assertIn("https://example.test/image.png", json.dumps(wire))
            self.assertEqual([item.model_dump() for item in messages], original)

    def test_write_collects_terminal_usage_and_original_response_metadata(self):
        class TerminalUsageModel(CaptureSourceModel):
            async def _astream(self, messages, **kwargs):
                async for chunk in super()._astream(messages, **kwargs):
                    yield chunk
                await asyncio.sleep(0.01)
                yield ChatGenerationChunk(message=AIMessageChunk(content="",
                    usage_metadata={"input_tokens": 9000, "output_tokens": 30, "total_tokens": 9030,
                                    "input_token_details": {"cache_read": 8000}},
                    response_metadata={"id": "resp_terminal", "finish_reason": "stop"}))
        session = agent.HtmlEditSession("<p>甲</p>")
        live = TerminalUsageModel(script=[{"tool": ("edit_file", {"path": "/article.html",
            "revision": session.source_file().revision, "edits": [{"old_text": "甲", "new_text": "乙"}]})},
            {"text": "完成"}], seen_messages=[], seen_message_counts=[], seen_schemas=[], seen_cache_keys=[])
        events = run(live, session)
        measured = [event["data"] for event in events if event["event"] == "context_stats"
                    and event["data"].get("state") == "measured"]
        self.assertEqual(session.html, "<p>乙</p>")
        self.assertEqual(len(measured), 2)
        self.assertEqual(measured[0]["used_tokens"], 9000)
        self.assertEqual(measured[0]["cached_input_tokens"], 8000)
        write_response = next(item for item in live.seen_messages[1]
                              if isinstance(item, AIMessage) and item.tool_calls)
        self.assertEqual(write_response.response_metadata["id"], "resp_terminal")

    def test_valid_write_with_missing_terminal_still_finishes_without_retry(self):
        session = agent.HtmlEditSession("<p>甲</p>")
        live = model([{"tool": ("edit_file", {"path": "/article.html",
            "revision": session.source_file().revision, "edits": [{"old_text": "甲", "new_text": "乙"}]}),
            "hang_after_tool": True}, {"text": "完成"}])
        with patch.object(agent, "MODEL_TOOL_TERMINAL_GRACE_SECONDS", 0.01):
            events = run(live, session)
        self.assertEqual(session.html, "<p>乙</p>")
        self.assertEqual(events[-1]["event"], "final")
        self.assertNotIn("model_turn_retry", [item["event"] for item in events])
        self.assertEqual(len(live.seen_messages), 2)

    def test_lazy_group_change_updates_state_and_then_reuses_schemas_and_key(self):
        session = agent.HtmlEditSession("<p>甲🙂</p>")
        chat_model = model([
            {"tool": ("read_file", {"path": "/article.html"})},
            {"tool": ("enable_tool_groups", {"groups": ["history", "images", "images"]})},
            {"tool": ("read_file", {"path": "/article.html"})},
            {"tool": ("enable_tool_groups", {"groups": ["images", "history"]})},
            {"tool": ("edit_file", {"path": "/article.html", "revision": session.source_file().revision,
                                    "edits": [{"old_text": "甲", "new_text": "乙"}]})},
            {"text": "完成"},
        ])
        events = run(chat_model, session)
        self.assertEqual(events[-1]["event"], "final")
        self.assertEqual(session.html, "<p>乙🙂</p>")
        self.assertEqual(chat_model.schema_bind_count, 2)
        self.assertEqual(chat_model.seen_schemas[0], chat_model.seen_schemas[1])
        self.assertTrue(all(schema == chat_model.seen_schemas[2] for schema in chat_model.seen_schemas[2:]))
        self.assertNotEqual(chat_model.seen_cache_keys[0], chat_model.seen_cache_keys[2])
        self.assertTrue(all(key == chat_model.seen_cache_keys[2] for key in chat_model.seen_cache_keys[2:]))
        self.assertTrue(chat_model.seen_cache_keys[0].startswith("yb-agent-v1-p7-m40-s3-src2-"))
        self.assertEqual(runtime_state(chat_model.seen_messages[0])["loaded_tool_groups"], [])
        self.assertEqual(runtime_state(chat_model.seen_messages[2])["loaded_tool_groups"], ["images", "history"])
        self.assertIs(chat_model.seen_messages[0][-1], chat_model.seen_messages[1][-1])
        self.assertIs(chat_model.seen_messages[2][-1], chat_model.seen_messages[3][-1])
        self.assertIs(chat_model.seen_messages[3][-1], chat_model.seen_messages[4][-1])
        self.assertIsNot(chat_model.seen_messages[4][-1], chat_model.seen_messages[5][-1])
        for messages in chat_model.seen_messages:
            self.assertEqual(messages[0].content, chat_model.seen_messages[0][0].content)
            self.assertEqual(sum(agent._is_runtime_context(item) for item in messages), 1)
            _assert_tool_pairing(self, messages[:-1])
        self.assertEqual(runtime_state(chat_model.seen_messages[-1])["files"][0]["revision"], session.source_file().revision)
        for messages in chat_model.seen_schemas[:2]:
            self.assertNotIn("inspect_current_images", [item["function"]["name"] for item in messages])

    def test_same_group_set_has_identical_schema_and_key_across_new_tasks(self):
        captured = []
        for groups, source in ((["history", "images", "images"], "<p>原稿</p>"),
                               (["images", "history"], "<p>新稿🙂</p>")):
            chat_model = model([{"text": "完成"}])
            run(chat_model, agent.HtmlEditSession(source), loaded_tool_groups=groups)
            captured.append(chat_model)
            self.assertEqual(groups, ["images", "history"])
        self.assertEqual(captured[0].seen_schemas, captured[1].seen_schemas)
        self.assertEqual(captured[0].seen_cache_keys, captured[1].seen_cache_keys)
        self.assertEqual(captured[0].seen_messages[0][0].content, captured[1].seen_messages[0][0].content)
        self.assertNotEqual(captured[0].seen_messages[0][-1].content, captured[1].seen_messages[0][-1].content)

    def test_schema_routing_key_reaches_both_openai_payload_formats(self):
        chat_model = model([{"text": "完成"}])
        run(chat_model, agent.HtmlEditSession("<p>正文</p>"))
        for responses in (True, False):
            live = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="unused",
                                            use_responses_api=responses,
                                            model_kwargs={"prompt_cache_key": "yb-agent-v1-p7-m40-s3"})
            bound = agent._bind_tools_with_prompt_cache(live, chat_model.seen_schemas[0],
                                                       prompt_cache_key=chat_model.seen_cache_keys[0])
            payload = bound.bound._get_request_payload(chat_model.seen_messages[0], **bound.kwargs)
            self.assertEqual(payload["prompt_cache_key"], chat_model.seen_cache_keys[0])
            self.assertNotIn(agent.RUNTIME_CONTEXT_MARKER, json.dumps(payload))
            self.assertNotIn("prompt_cache_breakpoint", json.dumps(payload))

    def test_parallel_group_loads_merge_and_invalid_groups_do_not_change_binding(self):
        chat_model = model([
            {"tools": [("enable_tool_groups", {"groups": ["history"]}),
                       ("enable_tool_groups", {"groups": ["images"]})]},
            {"tool": ("enable_tool_groups", {"groups": ["themes", "invalid"]})},
            {"text": "完成"},
        ])
        groups = []
        events = run(chat_model, agent.HtmlEditSession("<p>正文</p>"), loaded_tool_groups=groups)
        self.assertEqual(events[-1]["event"], "final")
        self.assertEqual(groups, ["images", "history"])
        self.assertEqual(runtime_state(chat_model.seen_messages[-1])["loaded_tool_groups"], groups)
        self.assertEqual(chat_model.seen_cache_keys[-1], chat_model.seen_cache_keys[-2])
        _assert_tool_pairing(self, chat_model.seen_messages[-1][:-1])

    def test_other_providers_disabled_flag_and_v1_keep_original_binding(self):
        for options in ({"prompt_cache_enabled": False},
                        {"provider_type": "gemini_native"}, {"tool_protocol": "v1"}):
            chat_model = model([{"text": "完成"}])
            run(chat_model, agent.HtmlEditSession("<p>正文</p>"), **options)
            self.assertEqual(chat_model.seen_cache_keys, [None])

    def test_loading_recalculates_absolute_schema_budget_and_duplicate_load_is_free(self):
        chat_model = model([{"tool": ("enable_tool_groups", {"groups": ["images"]})},
                            {"tool": ("enable_tool_groups", {"groups": ["images", "images"]})},
                            {"text": "完成"}])
        compactor = SimpleNamespace(ainvoke=AsyncMock())
        with patch.object(agent, "_agent_tool_schema_tokens", side_effect=[2_000, 5_500]) as schema_count:
            events = run(chat_model, agent.HtmlEditSession("<p>正文</p>"),
                         run_input_budget_tokens=50_000, compaction_model=compactor)
        self.assertEqual(schema_count.call_count, 2)
        requests = [item["data"] for item in events if item["event"] == "context_stats"
                    and item["data"].get("state") == "request_context"]
        self.assertEqual([item["tool_schema_tokens"] for item in requests], [2_000, 5_500, 5_500])
        self.assertEqual([item["input_budget_tokens"] for item in requests], [50_000, 50_000, 50_000])
        self.assertEqual([item["message_budget_tokens"] for item in requests], [48_000, 44_500, 44_500])
        compactor.ainvoke.assert_not_awaited()

    def test_preflight_budgets_current_group_state_on_resume(self):
        source = "<p>正文🙂</p>"
        configuration = SimpleNamespace(prompt_cache_enabled=True, tool_result_max_tokens=4096,
            provider=SimpleNamespace(provider_type=SimpleNamespace(value="openai_responses")))
        groups = ["themes", "images"]
        factory = agent.runtime_context_budget_factory(configuration, "源码缓存", source,
                    tool_protocol="v2", loaded_tool_groups=groups)
        fixed, state = factory({})
        chat_model = model([{"text": "完成"}])
        run(chat_model, agent.HtmlEditSession(source), loaded_tool_groups=groups)
        self.assertEqual(chat_model.seen_messages[0][0].content, fixed)
        self.assertEqual(chat_model.seen_messages[0][-1].content, state)
        self.assertEqual(runtime_state(chat_model.seen_messages[0])["loaded_tool_groups"], ["images", "themes"])

    def test_selection_reference_templates_and_image_placeholders_stay_in_latest_state(self):
        source = '<p>目标🙂</p><img src="data:image/png;base64,AAAA"/>'
        session = agent.HtmlEditSession(source)
        chat_model = model([{"tool": ("edit_file", {"path": "/article.html", "revision": session.source_file().revision,
            "edits": [{"old_text": "", "new_text": "<p>新增段落</p>", "start": 0, "end": 0}]})},
            {"text": "完成"}])
        events = run(chat_model, session,
            selected_elements=[{"selector": "p:nth-of-type(1)", "tag_name": "p", "text": "目标🙂", "html": "<p>目标🙂</p>"}],
            attached_templates=[{"id": 42, "name": "组件", "html": "<section>参考组件</section>"}],
            layout_reference={"html": "<p>外部参考</p>", "imitation_strength": "maximum"})
        self.assertEqual(events[-1]["event"], "final")
        before, after = (runtime_state(messages) for messages in chat_model.seen_messages)
        self.assertEqual(before["selections"][0]["start"], 0)
        self.assertEqual(after["selections"][0]["start"], len("<p>新增段落</p>"))
        self.assertEqual(after["selections"][0]["content"], "<p>目标🙂</p>")
        self.assertEqual(after["selections"][0]["revision"], session.source_file().revision)
        self.assertEqual(after["reference_mode"], "maximum")
        self.assertEqual(after["templates"], [{"label": "@组件1", "path": "/templates/42.html", "name": "组件"}])
        self.assertEqual({item["path"] for item in after["files"]}, {"/article.html", "/reference.html", "/templates/42.html"})
        self.assertIn("__YIBAN_INLINE_DATA_", session.source_file().content)
        self.assertEqual(chat_model.seen_cache_keys[0], chat_model.seen_cache_keys[1])
        self.assertEqual(chat_model.seen_messages[0][0].content, chat_model.seen_messages[1][0].content)

    def test_pause_restart_rebuilds_only_current_state_and_same_schema_key(self):
        source = '<p>正文</p><img src="data:image/png;base64,AAAA"/>'
        session = agent.HtmlEditSession(source)
        chat_model = model([{"tool": ("enable_tool_groups", {"groups": ["images"]})},
                            {"tool": ("ask_user", {"question": "继续吗？", "options": []})}])
        paused = run(chat_model, session)[-1]
        self.assertEqual(paused["event"], "user_question")
        data = paused["data"]
        self.assertEqual(data["loaded_tool_groups"], ["images"])
        stored = json.loads(json.dumps(data["resume_messages"], ensure_ascii=False))
        self.assertNotIn(agent._RUNTIME_CONTEXT_HEADER, json.dumps(stored, ensure_ascii=False))
        restarted = agent.HtmlEditSession(source.replace("正文", "最新正文"))
        resumed = model([{"text": "已继续"}])
        events = run(resumed, restarted, loaded_tool_groups=list(data["loaded_tool_groups"]),
            resume_messages=agent.restore_resume_messages(stored),
            resume_tool_result={"tool_call_id": data["tool_call_id"], "content": "继续"})
        self.assertEqual(events[-1]["event"], "final")
        self.assertEqual(resumed.seen_cache_keys[0], chat_model.seen_cache_keys[-1])
        self.assertEqual(resumed.seen_schemas[0], chat_model.seen_schemas[-1])
        messages = resumed.seen_messages[0]
        self.assertEqual(sum(agent._is_runtime_context(item) for item in messages), 1)
        self.assertEqual(runtime_state(messages)["files"][0]["revision"], restarted.source_file().revision)
        self.assertEqual(runtime_state(messages)["loaded_tool_groups"], ["images"])
        _assert_tool_pairing(self, messages[:-1])

    def test_legacy_selection_identity_loss_never_points_to_an_unrelated_sibling(self):
        legacy = [{"selector": "p:nth-of-type(1)", "tag_name": "p", "text": "目标🙂", "html": "<p>目标🙂</p>"}]
        for source, status in (("<p>新增</p><p>目标🙂</p><p>目标🙂</p>", "ambiguous"),
                               ("<p>新增</p><p>其他内容</p>", "missing")):
            state = source_selections(agent.HtmlEditSession(source), legacy)[0]
            self.assertEqual(state["status"], status)
            self.assertNotIn("start", state)
            self.assertNotIn("content", state)

    def test_compaction_preserves_loaded_group_state_without_putting_it_in_summary_input(self):
        source = "<p>最新正文</p>"
        session = agent.HtmlEditSession(source)
        cycles = []
        for index in range(9):
            call_id = f"source-{index}"
            cycles.extend([
                AIMessage(content="", tool_calls=[{"id": call_id, "name": "read_file",
                    "args": {"path": "/article.html"}}]),
                ToolMessage(content=json.dumps({"path": "/article.html", "revision": "old",
                    "content": "历史源码🙂 " * 1000}), name="read_file", tool_call_id=call_id),
            ])
        pending = AIMessage(content="", tool_calls=[{"id": "question", "name": "ask_user", "args": {}}])
        resume = [SystemMessage(content="old"), HumanMessage(content="真实请求"), *cycles, pending]
        schema = agent.editor_tool_schema_tokens("openai_responses", tool_protocol="v2", loaded_tool_groups=("images",))
        factory = agent.runtime_context_budget_factory(SimpleNamespace(prompt_cache_enabled=True, tool_result_max_tokens=4096,
            provider=SimpleNamespace(provider_type=SimpleNamespace(value="openai_responses"))),
            "源码缓存", source, tool_protocol="v2", loaded_tool_groups=["images"])
        fixed, state = factory({})
        hot = [SystemMessage(content=fixed), HumanMessage(content=state), resume[1], *resume[-6:]]
        required = sum(agent._provider_message_tokens(item, 1.6) for item in hot)
        compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
            field: "保留已完成修改" if field == "completed" else "" for field in agent._RUNTIME_SUMMARY_FIELDS}))))
        chat_model = model([{"tool": ("read_file", {"path": "/article.html"})}, {"text": "完成"}])
        events = run(chat_model, session, loaded_tool_groups=["images"], compaction_model=compactor,
            run_input_budget_tokens=required + schema + 1500,
            resume_messages=resume, resume_tool_result={"tool_call_id": "question", "content": "确认"})
        self.assertEqual(events[-1]["event"], "final")
        compactor.ainvoke.assert_awaited_once()
        self.assertNotIn(agent._RUNTIME_CONTEXT_HEADER, str(compactor.ainvoke.call_args.args[0]))
        self.assertEqual(chat_model.seen_cache_keys[0], chat_model.seen_cache_keys[1])
        for messages in chat_model.seen_messages:
            self.assertEqual(runtime_state(messages)["loaded_tool_groups"], ["images"])
            self.assertEqual(sum(isinstance(item, SystemMessage) for item in messages), 1)
            _assert_tool_pairing(self, messages[:-1])


if __name__ == "__main__":
    unittest.main()
