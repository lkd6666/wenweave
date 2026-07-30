"""Regression coverage for durable, provider-bounded tool output."""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import app.models  # noqa: F401 - register the complete metadata graph.
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.chat_tool_output import ChatToolOutput
from app.services.token_budget import estimate_tokens
from app.services.tool_output_store import ToolOutputError, ToolOutputStore, _now, cleanup_expired_tool_outputs


class ToolOutputStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine)
        self.db = Session(self.engine)
        self.store = ToolOutputStore(
            document_id=11,
            session_id=22,
            run_id="run-1",
            retention_days=7,
            storage_max_bytes=1024 * 1024,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def bind(self, content: str, limit: int = 512):
        with patch("app.services.tool_output_store.SessionLocal", self.Factory):
            return self.store.bind(
                tool_call_id="call-1",
                tool_name="diagnostic",
                content=content,
                max_preview_tokens=limit,
            )

    def test_large_result_is_stored_and_preview_is_provider_bounded(self) -> None:
        source = "\n".join(f"line {index}: " + ("内容" * 80) for index in range(300))

        binding = self.bind(source)

        self.assertTrue(binding.stored)
        self.assertIsNotNone(binding.output_id)
        self.assertLessEqual(estimate_tokens(binding.content), 512)
        preview = json.loads(binding.content)
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview["output_id"], binding.output_id)
        self.assertIn("read_tool_output", preview["next_step"])
        row = self.db.get(ChatToolOutput, binding.output_id)
        self.assertEqual(row.content, source)
        self.assertEqual(row.content_lines, 300)

    def test_large_chinese_preview_keeps_the_tail_without_spinning(self) -> None:
        """Theme libraries need a head/tail preview even when they exceed the cap."""
        source = ("主题组件示例：" + ("排版内容" * 48) + "\n") * 300 + "THEME-TAIL-MARKER"

        binding = self.bind(source, limit=512)

        preview = json.loads(binding.content)
        self.assertTrue(preview["truncated"])
        self.assertTrue(preview["preview"]["head"])
        self.assertIn("THEME-TAIL-MARKER", preview["preview"]["tail"])
        self.assertLessEqual(estimate_tokens(binding.content), 512)

    def test_pages_reconstruct_original_and_keep_cursor_opaque(self) -> None:
        source = "\n".join(f"{index:04d}=" + ("x" * 180) for index in range(70))
        binding = self.bind(source, limit=384)
        self.assertTrue(binding.output_id)
        cursor = None
        pages: list[str] = []
        while True:
            payload = json.loads(
                self.store.read_page(
                    self.db,
                    output_id=str(binding.output_id),
                    cursor=cursor,
                    max_tokens=384,
                )
            )
            self.assertLessEqual(estimate_tokens(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))), 384)
            pages.append(payload["content"])
            cursor = payload["next_cursor"]
            if cursor is None:
                break
        self.assertEqual("".join(pages), source)
        with self.assertRaises(ToolOutputError):
            self.store.read_page(self.db, output_id=str(binding.output_id), cursor="not-a-cursor", max_tokens=384)

    def test_preview_without_storage_never_replays_raw_large_content(self) -> None:
        source = "结果" * 2000
        binding = ToolOutputStore.preview_without_storage(content=source, max_preview_tokens=512)

        self.assertFalse(binding.stored)
        self.assertLessEqual(estimate_tokens(binding.content), 512)
        preview = json.loads(binding.content)
        self.assertTrue(preview["truncated"])
        self.assertNotIn("output_id", preview)

    def test_preview_without_storage_keeps_small_result_intact(self) -> None:
        source = '{"ok":true,"revision":"current"}'

        binding = ToolOutputStore.preview_without_storage(content=source, max_preview_tokens=512)

        self.assertEqual(binding.content, source)
        self.assertEqual(binding.original_tokens, estimate_tokens(source))

    def test_ttl_results_expire_and_are_removed(self) -> None:
        binding = self.bind("大结果\n" * 800)
        self.assertTrue(binding.output_id)
        other_session = ToolOutputStore(document_id=11, session_id=23, run_id="run-2")
        with self.assertRaisesRegex(ToolOutputError, "当前文档与对话"):
            other_session.read_page(self.db, output_id=str(binding.output_id), cursor=None, max_tokens=512)

        row = self.db.get(ChatToolOutput, binding.output_id)
        row.expires_at = _now() - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaisesRegex(ToolOutputError, "已过期"):
            self.store.read_page(self.db, output_id=str(binding.output_id), cursor=None, max_tokens=512)
        self.assertEqual(cleanup_expired_tool_outputs(self.db), 1)
        self.assertIsNone(self.db.get(ChatToolOutput, binding.output_id))

    def test_storage_ceiling_returns_a_recoverable_preview_without_persisting(self) -> None:
        store = ToolOutputStore(
            document_id=11,
            session_id=22,
            run_id="run-too-large",
            storage_max_bytes=256,
        )
        with patch("app.services.tool_output_store.SessionLocal", self.Factory):
            binding = store.bind(
                tool_call_id="call-large",
                tool_name="diagnostic",
                # Repeated bare ASCII is tokenized very compactly and would
                # not exercise the provider-preview branch at this limit.
                content="x " * 2048,
                max_preview_tokens=512,
            )
        self.assertFalse(binding.stored)
        preview = json.loads(binding.content)
        self.assertTrue(preview["truncated"])
        self.assertNotIn("output_id", preview)
        self.assertIn("可保存上限", preview["next_step"])


if __name__ == "__main__":
    unittest.main()
