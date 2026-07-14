import asyncio
import json
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.ai_model import AIModel
from app.models.chat_message import ChatMessage, MessageRole
from app.models.document_agent_memory import DocumentAgentMemory
from app.db.base import Base
from app.services.agent_context import AgentContextBuilder
from app.services.html_workspace import HtmlWorkspace
from app.schemas.ai_provider import ModelCreate


class AgentContextBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.model = AIModel(
            provider_id=1,
            model_name="test-model",
            display_name="Test",
            context_window_tokens=32768,
            context_compaction_threshold_tokens=16000,
            max_output_tokens=1000,
            tool_result_max_tokens=1000,
        )
        self.db.add(self.model)
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def add_turn(self, text: str, role: MessageRole) -> ChatMessage:
        message = ChatMessage(document_id=1, role=role, content=text)
        self.db.add(message)
        self.db.flush()
        return message

    def builder(self, rows: list[ChatMessage], prompt: str = "规则") -> AgentContextBuilder:
        return AgentContextBuilder(
            self.db,
            1,
            self.model,
            HtmlWorkspace("<section><h1>标题</h1><p>正文</p></section>"),
            rows,
            prompt,
        )

    def test_short_history_is_replayed_without_compaction(self) -> None:
        rows = [self.add_turn("请调整标题颜色", MessageRole.USER), self.add_turn("已完成", MessageRole.ASSISTANT)]

        prepared = asyncio.run(self.builder(rows).prepare())

        self.assertEqual(len(prepared.history), 2)
        self.assertEqual(prepared.stats["state"], "ready")
        self.assertIsNone(self.db.query(DocumentAgentMemory).first())

    def test_long_history_uses_deterministic_memory_and_keeps_recent_turns(self) -> None:
        rows: list[ChatMessage] = []
        for index in range(20):
            rows.append(self.add_turn(f"用户偏好 {index} " + "内容" * 900, MessageRole.USER))
            rows.append(self.add_turn(f"已完成第 {index} 轮 " + "结果" * 900, MessageRole.ASSISTANT))

        prepared = asyncio.run(self.builder(rows, "规则" * 1200).prepare())

        self.assertIn(prepared.stats["state"], {"compacted", "fallback_compacted"})
        self.assertLessEqual(len(prepared.history), 4)
        memory = self.db.query(DocumentAgentMemory).one()
        summary = json.loads(memory.summary_json)
        self.assertIn("user_preferences", summary)
        self.assertNotIn("<section", memory.summary_json)

    def test_superseded_covered_history_invalidates_memory(self) -> None:
        old_user = self.add_turn("旧偏好", MessageRole.USER)
        old_assistant = self.add_turn("旧结果", MessageRole.ASSISTANT)
        memory = DocumentAgentMemory(
            document_id=1,
            compacted_through_message_id=old_assistant.id,
            summary_json=json.dumps({"user_preferences": ["旧偏好"]}, ensure_ascii=False),
        )
        self.db.add(memory)
        self.db.commit()
        old_user.is_superseded = True
        self.db.commit()

        stats = self.builder([old_assistant]).snapshot()

        self.assertEqual(stats["state"], "ready")
        self.assertEqual(self.db.query(DocumentAgentMemory).one().compacted_through_message_id, 0)

    def test_smaller_model_reports_compaction_before_mutating_memory(self) -> None:
        self.model.context_window_tokens = 8192
        self.model.context_compaction_threshold_tokens = 7000
        rows: list[ChatMessage] = []
        for index in range(10):
            rows.append(self.add_turn(f"用户任务 {index} " + "内容" * 500, MessageRole.USER))
            rows.append(self.add_turn(f"完成情况 {index} " + "结果" * 500, MessageRole.ASSISTANT))

        stats = self.builder(rows).snapshot()

        self.assertTrue(stats["requires_compaction"])
        self.assertTrue(stats["can_fit_after_compaction"])
        self.assertEqual(stats["state"], "requires_compaction")
        self.assertIsNone(self.db.query(DocumentAgentMemory).first())

    def test_model_budget_schema_rejects_impossible_window(self) -> None:
        with self.assertRaises(ValidationError):
            ModelCreate(
                model_name="bad-budget",
                display_name="Bad budget",
                context_window_tokens=8192,
                context_compaction_threshold_tokens=7000,
                max_output_tokens=2000,
                tool_result_max_tokens=1000,
            )


if __name__ == "__main__":
    unittest.main()
