from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.services import chat_agent as agent
from app.services.html_workspace import HtmlWorkspace
from app.services.openai_compatible_chat_model import OpenAICompatibleChatModel, project_runtime_cache_messages
from tests.test_agent_loop_end_to_end import ScriptedChatModel
from tests.test_run_compaction import _assert_tool_pairing, _cycle


def run(model, session, **kwargs):
    enabled = kwargs.pop("prompt_cache_enabled", True)
    async def consume():
        return [event async for event in agent.run_agent_loop(
            model, "缓存测试", session.html, "保留正文并调整排版", session.document_map(),
            None, [], session=session, prompt_cache_enabled=enabled, **kwargs, tool_protocol="v1"
        )]
    return asyncio.run(consume())


class PromptCacheProjectionTests(unittest.TestCase):
    def test_continuous_local_writes_refresh_only_the_latest_state(self):
        source = "<section><p>first</p><p>second</p></section>"
        session = agent.HtmlEditSession(source)
        first = next(item for item in session.search("first")["results"] if item["tag"] == "p")
        second = next(item for item in session.search("second")["results"] if item["tag"] == "p")
        blocks = session.read_blocks([first["block_id"], second["block_id"]])["blocks"]
        hashes = {block["block_id"]: block["expected_hash"] for block in blocks}
        revisions = [session.workspace().revision, HtmlWorkspace.revision_for(source.replace("first", "FIRST"))]
        script = [{"tool": ("apply_html_patch", {"revision": revision, "operations": [
            {"block_id": block["block_id"], "expected_hash": hashes[block["block_id"]],
             "mode": "replace_inner", "html": replacement},
        ]})} for revision, block, replacement in zip(revisions, [first, second], ["FIRST", "SECOND"])]
        model = ScriptedChatModel(script=[*script, {"text": "完成"}], seen_messages=[], seen_message_counts=[])
        events = run(model, session, selected_elements=[{
            "selector": "section > p:nth-of-type(2)", "tag_name": "p", "text": "second", "html": "<p>second</p>",
        }])
        self.assertEqual(events[-1]["event"], "final")
        self.assertIn("<p>FIRST</p><p>SECOND</p>", session.html)
        self.assertEqual(len({messages[0].content for messages in model.seen_messages}), 1)
        snapshots = [messages[-1] for messages in model.seen_messages]
        for messages, snapshot in zip(model.seen_messages, snapshots):
            self.assertTrue(agent._is_runtime_context(snapshot))
            self.assertEqual(sum(agent._is_runtime_context(message) for message in messages), 1)
            self.assertNotIn("## 当前文档", messages[0].content)
            self.assertTrue(agent._is_user_request(messages[1]))
        for revision, snapshot in zip([*revisions, session.workspace().revision], snapshots):
            self.assertIn(revision, snapshot.content)
        self.assertNotIn("【最新运行状态", json.dumps(events[-1]["data"]["context_events"], ensure_ascii=False))

    def test_read_rounds_reuse_snapshot_and_meter_counts_it_once(self):
        session = agent.HtmlEditSession("<p>正文</p>")
        model = ScriptedChatModel(script=[{"tools": [("get_document_map", {}), ("search_html", {"query": "正文"})]},
                                          {"text": "完成"}], seen_messages=[], seen_message_counts=[])
        with patch.object(agent, "build_volatile_system_prompt", wraps=agent.build_volatile_system_prompt) as build:
            events = run(model, session)
        self.assertEqual(build.call_count, 1)
        self.assertIs(model.seen_messages[0][-1], model.seen_messages[1][-1])
        stats = [event["data"] for event in events if event["event"] == "context_stats" and event["data"].get("state") == "request_context"]
        for messages, stat in zip(model.seen_messages, stats):
            self.assertEqual(stat["used_tokens"], sum(agent._provider_message_tokens(message, 1)
                             for message in project_runtime_cache_messages(messages)))
        tools = [message for message in model.seen_messages[1] if isinstance(message, ToolMessage)]
        self.assertEqual(len(tools), 2)
        self.assertIsInstance(model.seen_messages[1][-2], ToolMessage)

    def test_budget_change_refreshes_snapshot_without_changing_system(self):
        session = agent.HtmlEditSession("<section>" + "".join(f"<p>段落{i}正文内容</p>" for i in range(100)) + "</section>")
        model = ScriptedChatModel(script=[{"tool": ("get_document_map", {})}, {"text": "完成"}],
                                  seen_messages=[], seen_message_counts=[])
        async def consume():
            async for event in agent.run_agent_loop(model, "测试", session.html, "检查", session.document_map(),
                                                   None, [], session=session, prompt_cache_enabled=True, tool_protocol="v1"):
                if event["event"] == "tool_result":
                    session.set_effective_tool_result_limit(512)
        asyncio.run(consume())
        self.assertEqual(model.seen_messages[0][0].content, model.seen_messages[1][0].content)
        self.assertLess(len(model.seen_messages[1][-1].content), len(model.seen_messages[0][-1].content))

    def test_legacy_providers_keep_their_original_prompt_path(self):
        for provider in ("gemini_native",):
            model = ScriptedChatModel(script=[{"text": "完成"}], seen_messages=[], seen_message_counts=[])
            run(model, agent.HtmlEditSession("<p>正文</p>"), provider_type=provider)
            self.assertIn("## 当前文档", model.seen_messages[0][0].content)
            self.assertFalse(any(agent._is_runtime_context(message) for message in model.seen_messages[0]))

    def test_runtime_marker_never_reaches_the_provider_or_resume_storage(self):
        context = HumanMessage(content="最新文档状态", additional_kwargs={agent.RUNTIME_CONTEXT_MARKER: True})
        for responses_api in (True, False):
            model = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="test", use_responses_api=responses_api)
            payload = model._get_request_payload([SystemMessage(content="固定规则"), HumanMessage(content="实际请求"), context])
            self.assertNotIn(agent.RUNTIME_CONTEXT_MARKER, json.dumps(payload))
        self.assertEqual(agent.serialise_resume_messages([HumanMessage(content="实际请求"), context]),
                         [{"type": "human", "content": "实际请求"}])
        head, cycles = agent._split_run_cycles([HumanMessage(content="实际请求"), AIMessage(content="工具步骤"), context])
        self.assertEqual(head[-1].content, "实际请求")
        self.assertFalse(any(agent._is_runtime_context(message) for cycle in cycles for message in cycle))
        self.assertNotIn("最新文档状态", agent._runtime_hot_transcript([HumanMessage(content="实际请求"), context], 1000))

    def test_old_question_resume_rebuilds_state_and_preserves_tool_pair(self):
        pending = AIMessage(content="", tool_calls=[{"id": "question", "name": "ask_user", "args": {}}])
        resume = [SystemMessage(content="OLD_SYSTEM_AND_REVISION"), HumanMessage(content="真实请求"), pending]
        model = ScriptedChatModel(script=[{"text": "继续完成"}], seen_messages=[], seen_message_counts=[])
        events = run(model, agent.HtmlEditSession("<p>恢复后的最新正文</p>"),
                     resume_messages=resume, resume_tool_result={"tool_call_id": "question", "content": "同意"})
        self.assertEqual(events[-1]["event"], "final")
        messages = model.seen_messages[0]
        self.assertNotIn("OLD_SYSTEM", messages[0].content)
        self.assertEqual(messages[-2].tool_call_id, "question")
        self.assertIn("恢复后的最新正文", messages[-1].content)

    def test_compaction_reserves_latest_state_and_never_receives_it_as_a_request(self):
        session = agent.HtmlEditSession("<p>最新正文</p>")
        model = ScriptedChatModel(script=[{"text": "完成"}], seen_messages=[], seen_message_counts=[])
        captured = []
        original = agent.compact_run_messages_with_model
        async def compact(messages, budget, *args, **kwargs):
            captured.append((messages, budget))
            return await original(messages, budget, *args, **kwargs)
        with patch.object(agent, "compact_run_messages_with_model", side_effect=compact):
            run(model, session, run_input_budget_tokens=30_000)
        messages, budget = captured[0]
        self.assertFalse(any(agent._is_runtime_context(message) for message in messages))
        self.assertEqual(messages[-1].content, "保留正文并调整排版")
        reserved = agent._provider_message_tokens(model.seen_messages[0][-1], 1)
        self.assertEqual(budget, 30_000 - reserved)

    def test_disabled_flag_and_model_switch_restore_legacy_projection(self):
        for enabled in (True, False, True):
            model = ScriptedChatModel(script=[{"text": "完成"}], seen_messages=[], seen_message_counts=[])
            run(model, agent.HtmlEditSession("<p>正文</p>"), prompt_cache_enabled=enabled)
            messages = model.seen_messages[0]
            self.assertEqual(sum(agent._is_runtime_context(message) for message in messages), int(enabled))
            self.assertEqual("## 当前文档" in messages[0].content, not enabled)

    def test_pause_serialise_restart_and_resume_rebuild_current_state(self):
        session = agent.HtmlEditSession("<p>暂停前正文</p>")
        model = ScriptedChatModel(script=[{"tool": ("ask_user", {"question": "请选择方向", "options": []})}],
                                  seen_messages=[], seen_message_counts=[])
        paused = run(model, session)[-1]
        self.assertEqual(paused["event"], "user_question")
        stored = json.loads(json.dumps(paused["data"]["resume_messages"], ensure_ascii=False))
        self.assertNotIn("【最新运行状态", json.dumps(stored, ensure_ascii=False))
        restored = agent.restore_resume_messages(stored)
        resumed = ScriptedChatModel(script=[{"text": "完成"}], seen_messages=[], seen_message_counts=[])
        run(resumed, agent.HtmlEditSession("<p>重启后的正文</p>"), resume_messages=restored,
            resume_tool_result={"tool_call_id": paused["data"]["tool_call_id"], "content": "确认"})
        messages = resumed.seen_messages[0]
        self.assertIn("重启后的正文", messages[-1].content)
        self.assertNotIn("暂停前正文", messages[-1].content)
        _assert_tool_pairing(self, messages[:-1])

    def test_images_and_reference_templates_stay_available_without_entering_system(self):
        image_url = "https://example.test/article.png"
        user_content = [{"type": "text", "text": "按附图调整"},
                        {"type": "image_url", "image_url": {"url": image_url}}]
        model = ScriptedChatModel(script=[{"tools": [("get_layout_reference_map", {}),
                                                     ("get_document_map", {})]}, {"text": "完成"}],
                                  seen_messages=[], seen_message_counts=[])
        events = run(model, agent.HtmlEditSession(f'<p>正文</p><img src="{image_url}">'),
                     user_content=user_content, model_is_multimodal=True,
                     layout_reference={"html": "<section><h1>参考标题</h1></section>", "title": "参考页面"},
                     attached_templates=[{"id": 17, "name": "卡片模板", "html": "<section>模板内容</section>"}])
        self.assertEqual(events[-1]["event"], "final")
        first = model.seen_messages[0]
        self.assertIn(image_url, json.dumps(first[1].content))
        self.assertIn("卡片模板", first[-1].content)
        self.assertNotIn("卡片模板", first[0].content)
        self.assertIn("get_layout_reference_map", model.bound_tool_names)
        _assert_tool_pairing(self, model.seen_messages[1][:-1])

    def test_real_runtime_compaction_keeps_request_state_and_complete_pairs(self):
        session = agent.HtmlEditSession("<p>最新正文</p>")
        pending = AIMessage(content="", tool_calls=[{"id": "question", "name": "ask_user", "args": {}}])
        resume = [SystemMessage(content="旧格式系统"), HumanMessage(content="保留正文并调整排版"),
                  *(message for index in range(8) for message in _cycle(index, payload_blocks=3)), pending]
        model = ScriptedChatModel(script=[{"tool": ("get_document_map", {})}, {"text": "完成"}],
                                  seen_messages=[], seen_message_counts=[])
        compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
            field: "保留已完成调整" if field == "completed" else ""
            for field in agent._RUNTIME_SUMMARY_FIELDS
        }))))
        # Use a real compactor and production multiplier; leave room for two
        # complete recent cycles plus a summary, but force older cycles out.
        system = agent.build_system_message(model, "缓存测试", session.html, static_only=True)
        state = HumanMessage(content=agent._RUNTIME_CONTEXT_HEADER + agent.build_volatile_system_prompt(
            "缓存测试", session.html, session.document_map()))
        budget = sum(agent._provider_message_tokens(message, agent.PROVIDER_TOKEN_ESTIMATE_SAFETY_MULTIPLIER)
                     for message in [system, state, resume[1], *resume[-6:]]) + 1_500
        with patch.object(agent, "_agent_tool_schema_tokens", return_value=0):
            events = run(model, session, resume_messages=resume,
                         resume_tool_result={"tool_call_id": "question", "content": "确认"},
                         compaction_model=compactor, run_input_budget_tokens=budget)
        self.assertEqual(events[-1]["event"], "final")
        compactor.ainvoke.assert_awaited_once()
        messages = model.seen_messages[0]
        self.assertEqual(messages[0].content, system.content)
        self.assertIn("保留正文并调整排版", [message.content for message in messages])
        self.assertEqual(sum(agent._is_runtime_context(message) for message in messages), 1)
        self.assertIn(session.workspace().revision, messages[-1].content)
        self.assertEqual(sum(isinstance(message, SystemMessage) for message in messages), 1)
        self.assertIsInstance(messages[1], AIMessage)
        for outgoing in model.seen_messages:
            self.assertEqual(sum(isinstance(message, SystemMessage) for message in outgoing), 1)
            self.assertEqual(sum(agent._is_runtime_context(message) for message in outgoing), 1)
        _assert_tool_pairing(self, messages[:-1])
        compact_input = compactor.ainvoke.call_args.args[0]
        self.assertNotIn("【最新运行状态", str(compact_input))
        self.assertLessEqual(sum(agent._provider_message_tokens(message, agent.PROVIDER_TOKEN_ESTIMATE_SAFETY_MULTIPLIER)
                                 for message in messages), budget)

    def test_tool_preview_budget_includes_latest_state_once(self):
        model = ScriptedChatModel(script=[{"tool": ("get_document_map", {})}, {"text": "完成"}],
                                  seen_messages=[], seen_message_counts=[])
        original = agent._dynamic_tool_result_limit
        with patch.object(agent, "_dynamic_tool_result_limit", wraps=original) as budget:
            run(model, agent.HtmlEditSession("<p>正文</p>"), run_input_budget_tokens=30_000)
        projection = budget.call_args.args[0]
        self.assertEqual(sum(agent._is_runtime_context(message) for message in projection), 1)
        self.assertEqual(projection[-1].content, model.seen_messages[0][-1].content)

    def test_preflight_reserves_the_new_projection_overhead_for_supported_models(self):
        legacy = agent.context_budget_prompt()
        stable = agent.context_budget_prompt(prompt_cache_enabled=True, provider_type="openai_responses")
        self.assertEqual(stable, legacy + agent._RUNTIME_CONTEXT_RULE + agent._RUNTIME_CONTEXT_HEADER)
        self.assertEqual(stable.count(agent._RUNTIME_CONTEXT_HEADER), 1)
        self.assertEqual(agent.context_budget_prompt(prompt_cache_enabled=True, provider_type="anthropic"), stable)
        for provider in ("gemini_native",):
            self.assertEqual(agent.context_budget_prompt(prompt_cache_enabled=True, provider_type=provider), legacy)


if __name__ == "__main__":
    unittest.main()
