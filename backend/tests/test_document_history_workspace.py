import asyncio
import unittest
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.document import Document
from app.models.document_version import DocumentVersionSource
from app.models.user import User, UserRole
from app.services.document_history_workspace import DocumentHistoryWorkspace, _HistoryWorkspaceCache
from app.services.document_versions import create_document_version
from app.services.html_workspace import HtmlWorkspace
from app.services.token_budget import estimate_tokens


class DocumentHistoryWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            username="history-reader",
            display_name="History Reader",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def make_document(self, html: str) -> Document:
        document = Document(
            owner_id=self.user.id,
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="历史版本测试",
            current_html=html,
        )
        self.db.add(document)
        self.db.flush()
        return document

    def commit_version(self, document: Document, html: str, label: str):
        document.current_html = html
        version = create_document_version(self.db, document, self.user.id, DocumentVersionSource.MANUAL, label)
        self.db.flush()
        return version

    def test_all_versions_are_reachable_beyond_first_page(self) -> None:
        document = self.make_document("<p>版本 0</p>")
        create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.flush()
        for index in range(1, 25):
            self.commit_version(document, f"<p>版本 {index}</p>", f"修改 {index}")

        history = DocumentHistoryWorkspace(self.db, document.id, 4_096)
        first_page = history.list_versions()
        second_page = history.list_versions(first_page["next_cursor"])

        self.assertEqual(first_page["total_versions"], 25)
        self.assertEqual(len(first_page["versions"]), 20)
        self.assertEqual(len(second_page["versions"]), 5)
        self.assertIsNone(second_page["next_cursor"])
        self.assertEqual(
            [item["version_number"] for item in [*first_page["versions"], *second_page["versions"]]],
            list(range(25, 0, -1)),
        )
        cursor = 0
        matches: list[dict] = []
        while True:
            search_page = history.search_versions("版本 0", cursor)
            matches.extend(search_page["matches"])
            if search_page["next_cursor"] is None:
                break
            cursor = search_page["next_cursor"]
        self.assertIn(1, [item["version"]["version_number"] for item in matches])

    def test_dynamic_budget_keeps_history_entries_whole_and_reachable(self) -> None:
        document = self.make_document("<p>版本 0</p>")
        create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.flush()
        for index in range(1, 18):
            self.commit_version(document, f"<p>版本 {index}</p>", f"第 {index} 次人工修改")

        history = DocumentHistoryWorkspace(self.db, document.id, 512)
        cursor = 0
        version_numbers: list[int] = []
        while True:
            page = history.list_versions(cursor)
            self.assertLessEqual(estimate_tokens(json.dumps(page, ensure_ascii=False, separators=(",", ":"))), 512)
            version_numbers.extend(item["version_number"] for item in page["versions"])
            if page["next_cursor"] is None:
                break
            self.assertGreater(page["next_cursor"], cursor)
            cursor = page["next_cursor"]

        self.assertEqual(version_numbers, list(range(18, 0, -1)))

    def test_search_compare_and_read_are_read_only(self) -> None:
        original = '<p>原始句子<img src="data:image/png;base64,AAAA"></p><p>保留段落</p>'
        document = self.make_document(original)
        initial = create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "原文")
        self.db.flush()
        current = "<p>改写后的句子</p><p>保留段落</p>"
        self.commit_version(document, current, "改写")
        history = DocumentHistoryWorkspace(self.db, document.id, 4_096)
        current_workspace = HtmlWorkspace(current, tool_result_max_tokens=4_096)

        search = history.search_versions("原始句子")
        comparison = history.compare_version(initial.id, current_workspace)
        historical_block_id = search["matches"][0]["block"]["block_id"]
        read = history.read_blocks(initial.id, [historical_block_id])

        self.assertEqual(search["matches"][0]["version"]["version_id"], initial.id)
        self.assertTrue(any(change["historical_text"] == "原始句子" for change in comparison["changes"]))
        self.assertIn("原始句子", read["blocks"][0]["html"])
        self.assertNotIn("data:image", read["blocks"][0]["html"])
        self.assertTrue(read["read_only"])
        self.assertEqual(current_workspace.source_html, current)

    def test_selected_version_image_search_and_inventory_are_complete_and_redacted(self) -> None:
        original = "".join(
            f'<p><img src="data:image/png;base64,IMAGE{index:02d}"></p>'
            for index in range(1, 5)
        )
        document = self.make_document(original)
        initial = create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "四张原图")
        self.db.flush()
        history = DocumentHistoryWorkspace(self.db, document.id, 4_096)

        search = history.search_version(initial.id, "img", limit=12)
        block_ids = [item["block_id"] for item in search["results"]]
        inventory = history.image_inventory(initial.id)
        read = history.read_blocks(initial.id, block_ids)

        self.assertEqual(search["match_count"], 4)
        self.assertEqual(len(block_ids), 4)
        self.assertEqual(inventory["image_count"], 4)
        self.assertEqual(inventory["unique_source_count"], 4)
        self.assertTrue(all(item["source_kind"] == "inline_data" for item in inventory["images"]))
        self.assertEqual([item["slot"] for item in inventory["images"]], [1, 2, 3, 4])
        self.assertEqual(len(read["blocks"]), 4)
        self.assertTrue(read["read_only"])
        self.assertNotIn("data:image", json.dumps(inventory, ensure_ascii=False))
        self.assertNotIn("data:image", json.dumps(read, ensure_ascii=False))

    def test_current_image_inventory_is_read_only(self) -> None:
        current = '<p><img src="https://cdn.example.com/a.png" srcset="https://cdn.example.com/a@2x.png 2x"></p><img>'
        workspace = HtmlWorkspace(current, tool_result_max_tokens=4_096)

        inventory = workspace.image_inventory()

        self.assertEqual(inventory["image_count"], 2)
        self.assertEqual(inventory["unique_source_count"], 1)
        self.assertEqual(inventory["images"][0]["source_kind"], "url")
        self.assertEqual(inventory["images"][0]["url_host"], "cdn.example.com")
        self.assertTrue(inventory["images"][0]["has_srcset"])
        self.assertEqual(inventory["images"][1]["source_kind"], "missing")
        self.assertEqual(workspace.source_html, current)
        self.assertNotIn("https://", json.dumps(inventory, ensure_ascii=False))

    def test_history_workspace_cache_reuses_and_evicts_immutable_versions(self) -> None:
        document = self.make_document("<p>版本 1</p>")
        first = create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "v1")
        self.db.flush()
        second = self.commit_version(document, "<p>版本 2</p>", "v2")
        third = self.commit_version(document, "<p>版本 3</p>", "v3")
        cache = _HistoryWorkspaceCache(max_entries=2, max_source_bytes=1_024)
        history = DocumentHistoryWorkspace(self.db, document.id, 4_096, workspace_cache=cache)

        history.search_version(first.id, "版本")
        history.search_version(second.id, "版本")
        history.search_version(third.id, "版本")
        history.search_version(second.id, "版本")

        metrics = history.cache_metrics()
        self.assertEqual(metrics["entries"], 2)
        self.assertEqual(metrics["evictions"], 1)
        self.assertGreaterEqual(metrics["hits"], 1)

    def test_history_workspace_cache_skips_oversized_source(self) -> None:
        oversized_html = "<p>" + ("x" * 256) + "</p>"
        document = self.make_document(oversized_html)
        version = create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "large")
        self.db.flush()
        cache = _HistoryWorkspaceCache(max_entries=2, max_source_bytes=64)
        history = DocumentHistoryWorkspace(self.db, document.id, 4_096, workspace_cache=cache)

        history.search_version(version.id, "x")
        history.search_version(version.id, "x")

        metrics = history.cache_metrics()
        self.assertEqual(metrics["entries"], 0)
        self.assertEqual(metrics["skipped_oversize"], 2)
        self.assertEqual(metrics["misses"], 2)

    def test_concurrent_history_reads_are_serialized_per_database_session(self) -> None:
        """ToolNode 并发调度时，不能并发使用同一个 SQLAlchemy Session。"""
        history = DocumentHistoryWorkspace(self.db, 1, 4_096)
        active_reads = 0
        maximum_concurrent_reads = 0
        state_lock = threading.Lock()
        version = SimpleNamespace(
            id=1,
            version_number=1,
            title="测试版本",
            source=DocumentVersionSource.MANUAL,
            label="测试",
            created_at=None,
        )

        def delayed_workspace(_: int):
            nonlocal active_reads, maximum_concurrent_reads
            with state_lock:
                active_reads += 1
                maximum_concurrent_reads = max(maximum_concurrent_reads, active_reads)
            try:
                time.sleep(0.03)
                return version, HtmlWorkspace("<p>历史内容</p>")
            finally:
                with state_lock:
                    active_reads -= 1

        async def read_in_parallel() -> list[dict]:
            return list(
                await asyncio.gather(
                    *(asyncio.to_thread(history.image_inventory, 1) for _ in range(8))
                )
            )

        with patch.object(history, "_workspace", side_effect=delayed_workspace):
            results = asyncio.run(read_in_parallel())

        self.assertEqual(maximum_concurrent_reads, 1)
        self.assertEqual(len(results), 8)

    def test_agent_history_read_retries_with_a_fresh_session_after_disconnect(self) -> None:
        first_session = SimpleNamespace(rollback=lambda: None, close=lambda: None)
        second_session = SimpleNamespace(rollback=lambda: None, close=lambda: None)
        sessions = [first_session, second_session]
        history = DocumentHistoryWorkspace(
            self.db,
            1,
            4_096,
            session_factory=lambda: sessions.pop(0),
        )
        disconnect = DBAPIError.instance(
            "SELECT document_versions.id",
            {},
            RuntimeError("Lost connection to MySQL server during query"),
            Exception,
            connection_invalidated=True,
        )
        version = SimpleNamespace(
            id=1,
            version_number=1,
            title="测试版本",
            source=DocumentVersionSource.MANUAL,
            label="测试",
            created_at=None,
        )

        with patch.object(
            DocumentHistoryWorkspace,
            "_workspace",
            side_effect=[disconnect, (version, HtmlWorkspace("<p>历史内容</p>"))],
        ):
            result = history.image_inventory(1)

        self.assertEqual(result["version"]["version_id"], 1)
        self.assertEqual(result["image_count"], 0)
        self.assertEqual(sessions, [])


if __name__ == "__main__":
    unittest.main()
