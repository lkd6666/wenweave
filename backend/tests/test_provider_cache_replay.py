"""Provider wire compatibility and immutable, revision-safe event replay."""
import asyncio
from dataclasses import replace
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.chat_session import ChatSession
from app.services import chat_agent as agent
from app.services.agent_context import AgentContextBuilder, ContextRecord
from app.services.html_workspace import HtmlWorkspace
from app.services.openai_compatible_chat_model import CACHE_BOUNDARIES_MARKER, OpenAICompatibleChatModel
from tests.test_source_prompt_cache import CaptureSourceModel, model, run


class ProviderCacheReplayTests(unittest.TestCase):
    def test_model_update_accepts_native_anthropic_opt_in_but_keeps_gemini_legacy(self):
        from fastapi import HTTPException
        from app.api.routes.ai_providers import _validate_prompt_cache_provider
        for protocol in (ProviderType.OPENAI_COMPATIBLE, ProviderType.OPENAI_RESPONSES, ProviderType.ANTHROPIC):
            _validate_prompt_cache_provider(SimpleNamespace(provider_type=protocol), True)
        with self.assertRaises(HTTPException):
            _validate_prompt_cache_provider(SimpleNamespace(provider_type=ProviderType.GEMINI_NATIVE), True)
        _validate_prompt_cache_provider(SimpleNamespace(provider_type=ProviderType.GEMINI_NATIVE), False)

    def test_non_gpt_protocols_use_user_state_without_assistant_prefill(self):
        for name, responses in (("deepseek-v4-flash", False), ("deepseek-v4-flash", True),
                                ("grok-4.6", False), ("gemini-3.8-flash", False), ("gpt-6.1-sol", True)):
            with self.subTest(name=name, responses=responses):
                transport = OpenAICompatibleChatModel(model=name, api_key="unused", use_responses_api=responses)
                state = HumanMessage(content="current revision", additional_kwargs={agent.RUNTIME_CONTEXT_MARKER: True})
                payload = transport._get_request_payload([SystemMessage(content="rules"), HumanMessage(content="task"), state])
                wire = payload["input" if responses else "messages"]
                self.assertEqual(wire[-1]["role"], "assistant" if name.startswith("gpt-") else "user")
                self.assertNotIn(agent.RUNTIME_CONTEXT_MARKER, json.dumps(payload))
                self.assertNotIn("partial", json.dumps(payload))

    def test_native_anthropic_cache_hints_are_projection_only_and_keep_tool_pairing(self):
        native = agent.ChatAnthropic(model="claude-sonnet-5", api_key="unused")
        system = agent.build_system_message(native, "title", "<p>old</p>", static_only=True, tool_protocol="v2")
        messages = [system, HumanMessage(content="task"), AIMessage(content="", tool_calls=[
            {"id": "a", "name": "read_file", "args": {}}, {"id": "b", "name": "list_files", "args": {}}]),
            ToolMessage(content="old source", name="read_file", tool_call_id="a"),
            ToolMessage(content="files", name="list_files", tool_call_id="b"),
            HumanMessage(content="latest revision", additional_kwargs={agent.RUNTIME_CONTEXT_MARKER: True,
                                                                      CACHE_BOUNDARIES_MARKER: False})]
        original = [m.model_dump() for m in messages]
        projected = agent._anthropic_history_cache_projection(messages)
        payload = native._get_request_payload(projected, tools=agent._anthropic_tools_with_cache_breakpoint([
            {"name": "read_file", "description": "read", "input_schema": {"type": "object", "properties": {}}}]))
        results = [block for m in payload["messages"] if isinstance(m["content"], list)
                   for block in m["content"] if isinstance(block, dict) and block.get("type") == "tool_result"]
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])
        self.assertNotIn("cache_control", results[0])
        self.assertIn("cache_control", results[1])
        self.assertNotIn("cache_control", str(payload["messages"][-1]["content"][-1]))
        self.assertEqual(json.dumps(payload).count('"cache_control"'), 3)
        self.assertNotIn(agent.RUNTIME_CONTEXT_MARKER, json.dumps(payload))
        self.assertEqual([m.model_dump() for m in messages], original)
        fallback = native._get_request_payload(agent._without_anthropic_cache_ttl(projected))
        self.assertNotIn('"ttl"', json.dumps(fallback))

    def test_image_only_history_cache_hint_falls_back_to_text_without_modifying_images(self):
        messages = [SystemMessage(content="rules"), HumanMessage(content="task"), AIMessage(content=[
            {"type": "thinking", "thinking": "actual thinking", "signature": "sig"}]),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}])]
        original = [m.model_dump() for m in messages]
        projected = agent._anthropic_history_cache_projection(messages)
        self.assertIn("cache_control", projected[1].content[0])
        self.assertEqual(projected[2:], messages[2:])
        self.assertEqual([m.model_dump() for m in messages], original)

    def test_deepseek_actual_reasoning_survives_resume_ledger_and_wire(self):
        response = AIMessage(content="", tool_calls=[{"id": "read", "name": "read_file", "args": {}}],
                             additional_kwargs={"reasoning_content": "actual provider reasoning"})
        result = ToolMessage(content="source", name="read_file", tool_call_id="read")
        resumed = agent.restore_resume_messages(agent.serialise_resume_messages([response, result]))
        event = agent.serialise_context_events(resumed)[0]
        replayed = ContextRecord(1, 1, event["kind"], event["payload"]).to_message("new", 512)
        self.assertEqual(replayed.additional_kwargs, response.additional_kwargs)
        for name in ("deepseek-v4-flash", "gpt-6.1-sol"):
            transport = OpenAICompatibleChatModel(model=name, api_key="unused")
            wire = transport._get_request_payload([HumanMessage(content="task"), replayed, result])["messages"]
            self.assertEqual(wire[1].get("reasoning_content"),
                             "actual provider reasoning" if name.startswith("deepseek") else None)
        without = response.model_copy(update={"additional_kwargs": {}})
        self.assertGreater(agent._provider_message_tokens(response, 1), agent._provider_message_tokens(without, 1))
        self.assertNotEqual(agent._message_token_fingerprint(response), agent._message_token_fingerprint(without))

    def test_builder_preserves_bounded_history_only_for_opted_in_protocols(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                provider = AIProvider(name="test", provider_type=ProviderType.OPENAI_RESPONSES, base_url="https://example.test",
                                      api_key_encrypted="unused")
                config = AIModel(provider=provider, model_name="test", display_name="test", context_window_tokens=100000,
                    context_compaction_threshold_tokens=80000, max_output_tokens=1000, tool_result_max_tokens=512)
                chat_session = ChatSession(document_id=1, title="test")
                db.add_all([provider, config, chat_session])
                db.flush()
                content = json.dumps({"path": "/article.html", "revision": "old", "content": "old source " * 1200})
                records = [ContextRecord(1, 1, "user", {"content": "task"}), ContextRecord(2, 2, "assistant", {
                    "content": "", "tool_calls": [{"id": "read", "name": "read_file", "args": {}}],
                    "reasoning_content": "actual reasoning"}), ContextRecord(3, 2, "tool", {
                        "content": content, "name": "read_file", "tool_call_id": "read"}, document_revision="old")]
                previous = None
                for enabled, protocol in ((True, ProviderType.OPENAI_RESPONSES), (True, ProviderType.ANTHROPIC),
                                          (False, ProviderType.OPENAI_RESPONSES), (True, ProviderType.GEMINI_NATIVE)):
                    provider.provider_type, config.prompt_cache_enabled = protocol, enabled
                    builder = AgentContextBuilder(db, 1, chat_session.id, config, HtmlWorkspace("<p>new</p>"), [], "rules", "next")
                    builder.records = builder._source_record_cache = records
                    prepared = asyncio.run(builder.prepare())
                    tool = prepared.history[-1]
                    preserve = enabled and protocol != ProviderType.GEMINI_NATIVE
                    self.assertEqual('"stale": true' not in tool.content, preserve)
                    self.assertLessEqual(agent.estimate_tokens(tool.content), 512)
                    if preserve:
                        self.assertIn("old source", tool.content)
                        if previous is not None:
                            self.assertEqual(previous, tool.content)
                        previous = tool.content
                    expected = sum(agent._provider_message_tokens(m, builder.token_estimate_multiplier) for m in prepared.history)
                    self.assertEqual(sum(builder._record_tokens(r) for r in records), expected)
                legacy = replace(records[-1], is_legacy=True)
                self.assertIn('"stale": true', legacy.to_message("new", 512, preserve_tool_history=True).content)
        finally:
            engine.dispose()

    def test_stale_preserved_revision_cannot_write_and_fresh_read_repairs(self):
        session = agent.HtmlEditSession("<p>current</p>")
        live = model([{"tool": ("edit_file", {"path": "/article.html", "revision": "old", "edits": [
            {"old_text": "current", "new_text": "updated"}]})},
            {"tool": ("read_file", {"path": "/article.html"})},
            {"tool": ("edit_file", {"path": "/article.html", "revision": session.source_file().revision, "edits": [
                {"old_text": "current", "new_text": "updated"}]})}, {"text": "done"}])
        events = run(live, session)
        self.assertEqual(session.html, "<p>updated</p>")
        self.assertEqual(events[-1]["event"], "final")
        self.assertIn("revision", live.seen_messages[1][-2].content)

    def test_write_usage_is_drained_on_enabled_and_legacy_paths(self):
        class Terminal(CaptureSourceModel):
            async def _astream(self, messages, **kwargs):
                async for chunk in super()._astream(messages, **kwargs):
                    yield chunk
                await asyncio.sleep(0.01)
                yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata={
                    "input_tokens": 9000, "output_tokens": 30, "total_tokens": 9030,
                    "input_token_details": {"cache_read": 8000}}))
        for enabled in (True, False):
            for protocol in ("openai_compatible", "openai_responses", "anthropic"):
                with self.subTest(enabled=enabled, protocol=protocol):
                    session = agent.HtmlEditSession("<p>old</p>")
                    live = Terminal(script=[{"tool": ("edit_file", {"path": "/article.html",
                        "revision": session.source_file().revision, "edits": [{"old_text": "old", "new_text": "new"}]})},
                        {"text": "done"}], seen_messages=[], seen_message_counts=[], seen_schemas=[], seen_cache_keys=[])
                    events = run(live, session, prompt_cache_enabled=enabled, provider_type=protocol)
                    usage = [e["data"] for e in events if e["event"] == "context_stats" and e["data"].get("state") == "measured"]
                    self.assertEqual(len(usage), 2)
                    self.assertEqual(usage[0]["cached_input_tokens"], 8000)
                    self.assertEqual(session.html, "<p>new</p>")

    def test_write_recovery_keeps_actual_reasoning_when_terminal_usage_is_missing(self):
        class ReasoningWithoutUsage(CaptureSourceModel):
            async def _astream(self, messages, **kwargs):
                yield ChatGenerationChunk(message=AIMessageChunk(content="", additional_kwargs={
                    "reasoning_content": "actual provider reasoning"}))
                async for chunk in super()._astream(messages, **kwargs):
                    yield chunk
        for enabled in (True, False):
            session = agent.HtmlEditSession("<p>old</p>")
            live = ReasoningWithoutUsage(script=[{"tool": ("edit_file", {"path": "/article.html",
                "revision": session.source_file().revision, "edits": [{"old_text": "old", "new_text": "new"}]}),
                "hang_after_tool": True}, {"text": "done"}], seen_messages=[], seen_message_counts=[],
                seen_schemas=[], seen_cache_keys=[])
            with patch.object(agent, "MODEL_TOOL_TERMINAL_GRACE_SECONDS", 0.01):
                events = run(live, session, prompt_cache_enabled=enabled, provider_type="openai_compatible")
            write = next(m for m in live.seen_messages[1] if isinstance(m, AIMessage) and m.tool_calls)
            self.assertEqual(write.additional_kwargs["reasoning_content"], "actual provider reasoning")
            self.assertEqual(session.html, "<p>new</p>")
            self.assertEqual(events[-1]["event"], "final")


if __name__ == "__main__":
    unittest.main()
