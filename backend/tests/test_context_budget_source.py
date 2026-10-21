"""The preflight budget must price the same source request as the live graph."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.chat import _merge_runtime_context_stats
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.chat_context_event import ContextEventKind
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_session import ChatSession
from app.schemas.chat import ChatContextStatsRead
from app.services import chat_agent as agent
from app.services.agent_context import AgentContextBuilder, ContextRecord
from app.services.chat_images import user_message_content
from app.services.html_workspace import HtmlWorkspace
from tests.test_source_prompt_cache import model


class SourceContextBudgetTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.configuration = AIModel(provider_id=1, model_name="budget", display_name="budget",
            context_window_tokens=100_000, context_compaction_threshold_tokens=80_000,
            max_output_tokens=10_000, tool_result_max_tokens=4096, is_multimodal=True)
        self.session = ChatSession(document_id=1, title="预算")
        self.db.add_all([self.configuration, self.session])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def builder(self, factory, **kwargs):
        return AgentContextBuilder(self.db, 1, self.session.id, self.configuration,
            HtmlWorkspace("<p>正文🙂</p>"), [], "obsolete budget prompt", current_request="继续局部排版",
            additional_context="不应重复计数的旧选中元素 JSON" * 100, runtime_context_factory=factory, **kwargs)

    def test_preflight_and_graph_match_for_enabled_disabled_and_other_providers(self):
        selection = [{"selector": "p:nth-of-type(1)", "tag_name": "p", "text": "正文🙂", "html": "<p>正文🙂</p>"}]
        templates = [{"id": 7, "name": "卡片", "html": "<section>参考模板</section>"}]
        reference = {"title": "参考", "html": "<p>参考🙂</p>"}
        image_context = {"image_model_id": 7, "model_name": "当前图片模型🙂"}
        groups = ["images", "history"]
        records = [
            ContextRecord(1, 1, ContextEventKind.USER.value, {"content": "保持全部正文"}),
            ContextRecord(2, 2, ContextEventKind.ASSISTANT.value, {"content": "", "tool_calls": [
                {"id": "read-1", "name": "read_file", "args": {"path": "/article.html"}}], "private": "账本字段不发给模型" * 500}),
            ContextRecord(3, 2, ContextEventKind.TOOL.value, {"name": "read_file", "tool_call_id": "read-1", "content": "已读正文"}),
        ]
        cases = [(enabled, provider, protocol) for protocol in ("v1", "v2")
                 for enabled, provider in [(True, "openai_responses"), (False, "openai_responses"),
                                           (True, "anthropic"), (True, "gemini_native")]]
        for enabled, provider, protocol in cases:
            with self.subTest(enabled=enabled, provider=provider, protocol=protocol):
                config = SimpleNamespace(prompt_cache_enabled=enabled, tool_result_max_tokens=4096,
                    provider=SimpleNamespace(provider_type=SimpleNamespace(value=provider)))
                factory = agent.runtime_context_budget_factory(config, "预算测试", "<p>正文🙂</p>",
                    selected_elements=selection, attached_templates=templates, layout_reference=reference,
                    image_generation_context=image_context,
                    loaded_tool_groups=groups, tool_protocol=protocol)
                schema = agent.editor_tool_schema_tokens(provider, True, tool_protocol=protocol, loaded_tool_groups=tuple(groups))
                builder = self.builder(factory, tool_schema_tokens=schema)
                builder.records = records
                builder._source_record_cache = records
                compactor = SimpleNamespace(ainvoke=AsyncMock())
                prepared = asyncio.run(builder.prepare(compactor))
                chat_model = model([{"text": "完成"}])

                async def consume():
                    return [event async for event in agent.run_agent_loop(chat_model, "预算测试", "<p>正文🙂</p>",
                        "继续局部排版", prepared.workspace_map, prepared.memory, prepared.history, selection, reference,
                        session=agent.HtmlEditSession("<p>正文🙂</p>", 4096), attached_templates=templates,
                        image_generation_context=image_context,
                        loaded_tool_groups=list(groups), tool_protocol=protocol, provider_type=provider,
                        prompt_cache_enabled=enabled, compaction_model=compactor,
                        run_input_budget_tokens=prepared.stats["active_context_threshold_tokens"])]

                events = asyncio.run(consume())
                request = next(event["data"] for event in events if event["event"] == "context_stats"
                               and event["data"].get("state") == "request_context")
                runtime = _merge_runtime_context_stats(prepared.stats, request)
                self.assertEqual(runtime["used_tokens"], prepared.stats["used_tokens"])
                self.assertEqual(sum(runtime["runtime_context_breakdown"].values()), runtime["used_tokens"])
                self.assertEqual(runtime["active_context_threshold_tokens"], 80_000)
                self.assertGreater(runtime["runtime_context_breakdown"]["runtime_state"], 0)
                self.assertEqual(prepared.stats["breakdown"]["selected_context"], 0)
                self.assertNotIn("账本字段", str(chat_model.seen_messages))
                compactor.ainvoke.assert_not_awaited()

    def test_inline_image_names_and_fixed_charge_match_provider_projection(self):
        factory = agent.runtime_context_budget_factory(SimpleNamespace(prompt_cache_enabled=True, tool_result_max_tokens=4096,
            provider=SimpleNamespace(provider_type=SimpleNamespace(value="openai_responses"))), "预算测试", "<p>正文🙂</p>", tool_protocol="v2")
        attachments = [ChatImageAttachment(id="image-1", document_id=1, uploader_id=1, filename="中文配图🙂.png",
            content_type="image/png", size=10, storage_mode="local", object_key="example.png", is_direct_input=True)]
        builder = self.builder(factory, tool_schema_tokens=0, current_image_attachments=attachments)
        stats = builder._stats({}, [], "ready", None)
        fixed, state = factory({})
        with patch("app.services.chat_images.image_content_blocks", return_value=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]):
            content = user_message_content(self.db, "继续局部排版", attachments, provider_type="openai_responses",
                                           include_images=True, image_limit=stats["image_loading"]["current_inline_count"])
        expected = (builder._provider_text_tokens(fixed) + builder._provider_text_tokens(state)
                    + agent._provider_message_tokens(HumanMessage(content=content), 1.6))
        self.assertEqual(stats["used_tokens"], expected)
        self.assertEqual(sum(stats["breakdown"].values()), expected)
        self.assertEqual(stats["breakdown"]["image_inputs"], 1024)

    def test_output_reserve_is_applied_once_and_api_preserves_budget_metadata(self):
        self.configuration.context_compaction_threshold_tokens = 99_000
        builder = self.builder(None, budget_multiplier=0.5, tool_schema_tokens=2000)
        stats = ChatContextStatsRead.model_validate(builder.snapshot()).model_dump()
        self.assertEqual(stats["input_limit_tokens"], 90_000)
        self.assertEqual(stats["usable_tokens"], 90_000)
        self.assertEqual(stats["active_context_threshold_tokens"], 45_000)
        self.assertEqual(stats["token_estimate_multiplier"], 1.6)
        self.assertEqual(stats["model_id"], self.configuration.id)
        self.assertEqual(agent._effective_run_input_budget(45_000, 2000), 43_000)
        measured = _merge_runtime_context_stats(stats, {"state": "measured", "used_tokens": 0, "cached_input_tokens": 0})
        self.assertTrue(measured["last_model_usage_reported"])
        self.assertEqual(measured["runtime_input_tokens"], 0)
        self.assertEqual(measured["used_tokens"], stats["used_tokens"])


if __name__ == "__main__":
    unittest.main()
