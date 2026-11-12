"""Checkpoints preserve recovery and pairing; normal turns preserve cache prefixes."""
from __future__ import annotations

import asyncio
import json
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import app.models  # noqa: F401
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.chat_tool_output import ChatToolOutput
from app.services.context_projection import (
    RECEIPT_KEY, bind_context_tool_result, cycle_checkpoint_receipts,
    tool_receipt,
)
from app.services.chat_agent import compact_run_messages_with_model, _run_message_tokens, RuntimeCompactionError
from app.services.tool_output_store import ToolOutputStore, ToolOutputError, _now
from app.services.source_workspace import SourceFile, read_source, apply_replacements
from app.services.token_budget import estimate_tokens
from tests import test_run_compaction as run_tests
from tests import test_source_prompt_cache as source_tests


class ContextProjectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.store = ToolOutputStore(document_id=1, session_id=2, run_id="projection-test")
        self.patch = patch("app.services.tool_output_store.SessionLocal", self.factory)
        self.patch.start()
        self.source = SourceFile("/article.html", "<p>保留正文</p>\n" * 800)
        self.compactor = run_tests.RunCompactionTests._Compactor()
        self.compactor.ainvoke = AsyncMock(wraps=self.compactor.ainvoke)

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()

    def cycle(self, index=1, name="read_file", payload=None):
        payload = payload if payload is not None else read_source(self.source, budget=30_000)
        original = ToolMessage(name=name, tool_call_id=f"call-{index}", content=json.dumps(payload, ensure_ascii=False))
        bound = bind_context_tool_result(original, tool_name=name, max_tokens=30_000, store=self.store)
        return [AIMessage(content="", tool_calls=[{"id": original.tool_call_id, "name": name,
                    "args": {"path": "/article.html"}}]), bound]

    def recover(self, output_id):
        parts, cursor = [], None
        with self.factory() as db:
            while True:
                page = json.loads(self.store.read_page(db, output_id=output_id, cursor=cursor, max_tokens=600))
                parts.append(page["content"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
        return "".join(parts)

    def test_first_result_is_readable_and_archive_recovers_exact_original(self):
        cycle = self.cycle()
        result = json.loads(cycle[-1].content)
        self.assertEqual(result["content"], self.source.content)
        receipt = tool_receipt(cycle[-1])
        self.assertEqual(json.loads(self.recover(receipt["output_id"])), read_source(self.source, budget=30_000))
        self.assertEqual(result["output_id"], receipt["output_id"])
        self.assertEqual(receipt["facts"]["revision"], self.source.revision)

    def test_disabled_compaction_preserves_delivered_history_with_recovery_handles(self):
        first, latest = self.cycle(), self.cycle(2)
        messages = [SystemMessage(content="规则"), HumanMessage(content="改标题"), *first, *latest]
        originals = [message.model_dump() for message in messages]
        projected, stats = asyncio.run(compact_run_messages_with_model(messages, 0, self.compactor))
        self.assertFalse(stats["compacted"])
        self.assertEqual(projected, messages)
        receipt = tool_receipt(projected[3])
        self.assertEqual(receipt["facts"]["start"], 0)
        self.assertIn(self.source.content, json.loads(self.recover(receipt["output_id"]))["content"])
        self.assertEqual([message.model_dump() for message in messages], originals)
        run_tests._assert_tool_pairing(self, projected)
        self.compactor.ainvoke.assert_not_awaited()

    def test_under_threshold_preserves_exact_history_and_does_not_call_summarizer(self):
        messages = [HumanMessage(content="改标题"), *self.cycle(), *self.cycle(2)]
        original = [item.model_dump() for item in messages]
        outgoing, stats = asyncio.run(compact_run_messages_with_model(messages, 100_000, self.compactor))
        self.assertFalse(stats["compacted"])
        self.assertEqual([item.model_dump() for item in outgoing], original)
        self.assertEqual(stats["used_tokens"], _run_message_tokens(outgoing, 1, 0))
        self.compactor.ainvoke.assert_not_awaited()

    def test_deep_checkpoint_covers_latest_and_keeps_server_recovery_even_if_model_omits_it(self):
        latest = self.cycle(2)
        messages = [SystemMessage(content="规则"), HumanMessage(content="正文保留"), *self.cycle(), *latest]
        originals = [message.model_dump() for message in messages]
        outgoing, stats = asyncio.run(compact_run_messages_with_model(
            messages, _run_message_tokens(messages, 1.6, 0), self.compactor, token_estimate_multiplier=1.6))
        self.assertTrue(stats["latest_cycle_checkpointed"])
        self.assertEqual(stats["summarized_cycles"], 2)
        self.assertFalse(any(isinstance(item, ToolMessage) for item in outgoing))
        self.assertEqual(outgoing[-1], messages[1])
        receipt = tool_receipt(latest[-1])
        self.assertIn(receipt["source_ref"], stats["summary"])
        from app.api.routes.chat import _runtime_summary_memory
        self.assertIn(receipt["source_ref"], _runtime_summary_memory(stats["summary"])["source_refs"])
        self.assertIn(self.source.revision, stats["summary"])
        self.assertLessEqual(stats["used_tokens"], stats["compaction_target_tokens"])
        self.assertTrue(any(latest[-1].content in str(call.args[0][-1].content)
                            for call in self.compactor.ainvoke.await_args_list))
        self.assertEqual([message.model_dump() for message in messages], originals)
        # Continue with the exact historical payload and current source identity.
        original = json.loads(self.recover(receipt["output_id"]))
        self.assertEqual(original["revision"], self.source.revision)
        current = read_source(self.source, start=0, end=20)
        updated, _ = apply_replacements(self.source.content, [{"start": 3, "end": 7, "old_text": "保留正文", "new_text": "新的正文"}])
        self.assertEqual(current["revision"], self.source.revision)
        self.assertTrue(updated.startswith("<p>新的正文</p>"))
        run_tests._assert_tool_pairing(self, outgoing)
        continued_input = [*outgoing, *self.cycle(3)]
        calls_before = self.compactor.ainvoke.await_count
        continued, continuation = asyncio.run(compact_run_messages_with_model(
            continued_input, _run_message_tokens(messages, 1.6, 0), self.compactor, token_estimate_multiplier=1.6))
        self.assertFalse(continuation["compacted"])
        self.assertEqual([item.model_dump() for item in continued], [item.model_dump() for item in continued_input])
        self.assertEqual(self.compactor.ainvoke.await_count, calls_before)

    def test_latest_error_control_visual_or_incomplete_cycle_is_protected(self):
        for name, payload in (("read_file", {"ok": False, "error": "revision conflict"}),
                              ("edit_file", {"ok": True, "warnings": ["HTML 不合法"]}),
                              ("ask_user", {"answer": "只改标题"}),
                              ("enable_tool_groups", {"ok": True, "groups": ["images"]})):
            with self.subTest(name=name):
                cycle = self.cycle(8, name, payload)
                self.assertIsNone(cycle_checkpoint_receipts(cycle))
        complete = self.cycle()
        self.assertIsNone(cycle_checkpoint_receipts(complete[:1]))
        self.assertIsNone(cycle_checkpoint_receipts([*complete, HumanMessage(content=[{"type": "image_url", "image_url": "x"}])]))
        self.assertIsNone(cycle_checkpoint_receipts([complete[0], complete[1].model_copy(update={"tool_call_id": "wrong"})]))

    def test_parallel_cycle_requires_every_answer_and_receipt(self):
        a, b = self.cycle(), self.cycle(2)
        call = AIMessage(content="", tool_calls=[*a[0].tool_calls, *b[0].tool_calls])
        self.assertEqual(len(cycle_checkpoint_receipts([call, a[1], b[1]])), 2)
        self.assertIsNone(cycle_checkpoint_receipts([call, a[1]]))
        self.assertIsNone(cycle_checkpoint_receipts([call, a[1], a[1]]))

    def test_expired_or_unstored_output_never_authorizes_eviction(self):
        cycle = self.cycle()
        receipt = tool_receipt(cycle[-1])
        expired = {**receipt, "expires_at": (_now() - timedelta(seconds=1)).isoformat()}
        changed = cycle[-1].model_copy(update={"additional_kwargs": {RECEIPT_KEY: expired}})
        self.assertIsNone(tool_receipt(changed))
        self.assertIsNone(tool_receipt(cycle[-1].model_copy(update={"additional_kwargs": {}})))
        failing = ToolOutputStore(document_id=1, session_id=2, run_id="no-space", storage_max_bytes=1)
        original = ToolMessage(content=json.dumps(read_source(self.source, budget=30_000)), tool_call_id="raw")
        bound = bind_context_tool_result(original, tool_name="read_file", max_tokens=30_000, store=failing)
        self.assertIsNone(tool_receipt(bound))
        self.assertEqual(bound.content, original.content)

    def test_recovery_page_is_consumed_once_and_does_not_create_another_archive(self):
        first = self.cycle()
        receipt = tool_receipt(first[-1])
        with self.factory() as db:
            page = json.loads(self.store.read_page(db, output_id=receipt["output_id"], cursor=None, max_tokens=600))
        recovered = self.cycle(2, "read_tool_output", page)
        self.assertIsNone(cycle_checkpoint_receipts(recovered))
        self.assertIsNotNone(tool_receipt(recovered[-1]))
        with self.factory() as db:
            self.assertEqual(db.query(ChatToolOutput).count(), 1)

    def test_failed_checkpoint_preserves_input_and_cross_session_read_is_rejected(self):
        messages = [HumanMessage(content="保留正文"), *self.cycle()]
        originals = [message.model_dump() for message in messages]
        broken = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("unavailable")))
        with self.assertRaises(RuntimeCompactionError):
            asyncio.run(compact_run_messages_with_model(messages, 3000, broken))
        self.assertEqual([message.model_dump() for message in messages], originals)
        other = ToolOutputStore(document_id=1, session_id=3, run_id="other")
        with self.factory() as db, self.assertRaises(ToolOutputError):
            other.read_page(db, output_id=tool_receipt(messages[-1])["output_id"], cursor=None, max_tokens=600)

    def test_successful_write_checkpoint_preserves_validation_and_no_duplicate_write(self):
        cycle = self.cycle(1, "write_file", {"ok": True, "revision": "new", "validation": {"ok": True}})
        cycle[0] = AIMessage(content="", tool_calls=[{"id": "call-1", "name": "write_file",
                    "args": {"path": "/article.html", "content": self.source.content}}])
        outgoing, stats = asyncio.run(compact_run_messages_with_model(
            [HumanMessage(content="重排文章"), *cycle], 3000, self.compactor))
        self.assertTrue(stats["latest_cycle_checkpointed"])
        self.assertIn('validation', stats["summary"])
        self.assertFalse(any(getattr(message, "tool_calls", None) for message in outgoing))

    def test_real_graph_preserves_wire_prefix_with_archived_outputs(self):
        from app.services.chat_agent import HtmlEditSession
        model = source_tests.model([
            {"tool": ("read_file", {"path": "/article.html"})},
            {"tool": ("read_file", {"path": "/article.html"})},
            {"text": "已核对"},
        ])
        source_tests.run(model, HtmlEditSession(self.source.content),
                         tool_output_store=self.store, run_input_budget_tokens=100_000,
                         compaction_model=self.compactor)
        first_view = next(item for item in model.seen_messages[1] if isinstance(item, ToolMessage))
        third_view = [item for item in model.seen_messages[2] if isinstance(item, ToolMessage)]
        self.assertIn("content", json.loads(first_view.content))
        self.assertEqual(third_view[0].content, first_view.content)
        self.assertIn("content", json.loads(third_view[-1].content))
        from app.services.openai_compatible_chat_model import OpenAICompatibleChatModel
        # Compare actual serialized request messages, not internal metadata
        # hashes or mocked cache usage. The changing live-state suffix is last.
        for responses in (False, True):
            transport = OpenAICompatibleChatModel(model="gpt-6.1-sol", api_key="unused", use_responses_api=responses)
            key = "input" if responses else "messages"
            before = transport._get_request_payload(model.seen_messages[1])[key][:-1]
            after = transport._get_request_payload(model.seen_messages[2])[key]
            self.assertEqual(before, after[:len(before)])
        self.compactor.ainvoke.assert_not_awaited()

    def test_storage_retry_cannot_rebind_a_changed_result_to_the_old_object(self):
        first = self.cycle()
        different = self.cycle(payload={"path": "/article.html", "revision": "new",
                                        "content": "different " * 4000})
        self.assertIsNotNone(tool_receipt(first[-1]))
        self.assertIsNone(tool_receipt(different[-1]))
        self.assertNotEqual(json.loads(first[-1].content)["content"], json.loads(different[-1].content)["content"])

    def test_small_reads_stay_inline_without_archive_overhead(self):
        small = self.cycle(payload={"path": "/article.html", "revision": "r1", "content": "<p>短文</p>"})
        self.assertIsNone(tool_receipt(small[-1]))
        self.assertNotIn("output_id", json.loads(small[-1].content))
        with self.factory() as db:
            self.assertEqual(db.query(ChatToolOutput).count(), 0)

    def test_archive_handle_never_breaks_a_full_contiguous_source_page(self):
        payload = read_source(self.source, budget=2000)
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        original = ToolMessage(name="read_file", tool_call_id="tight-page", content=content)
        bound = bind_context_tool_result(original, tool_name="read_file", max_tokens=estimate_tokens(content), store=self.store)
        self.assertEqual(bound.content, content)
        self.assertIsNotNone(tool_receipt(bound))
        self.assertEqual(json.loads(bound.content)["next_cursor"], payload["end"])


if __name__ == "__main__":
    unittest.main()
