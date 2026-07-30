import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.gzh_themes import list_gzh_themes
from app.db.base import Base
from app.models.gzh_theme import GzhTheme, GzhThemeGeneration, GzhThemeGenerationStatus, GzhThemeStatus
from app.models.gzh_theme_proposal import GzhThemeProposalStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.user import UserRole
from app.services.gzh_theme import (
    GzhThemeError,
    approve_proposal,
    build_theme_manifest,
    consume_approved_proposal,
    create_proposal,
    latest_applied_theme_proposal,
    lint_theme_source,
    list_themes,
    proposal_theme_payload,
    reask_theme_proposal_id,
    resolve_theme,
    validate_gzh_html,
)
from app.services.gzh_theme_generation import (
    GzhThemeGenerationError,
    publish_theme_version,
    save_generation_as_draft,
    validate_generated_package,
)


GENERATED_SOURCE = """# 测试主题

## 设计变量速查表

- 主色: #1677ff

## 组件 1 封面

```html
<section style="padding:16px"><p><span leaf="">封面标题</span></p></section>
```

## 组件 2 章节标题

```html
<section style="padding:12px"><h2><span leaf="">章节标题</span></h2></section>
```

## 组件 3 正文段落

```html
<p style="line-height:1.8"><span leaf="">正文内容</span></p>
```

## 组件 4 引用

```html
<section style="padding:12px;border-left:3px solid #1677ff"><p><span leaf="">引用内容</span></p></section>
```

## 完整文章模板骨架

封面 → 章节标题 → 正文 → 引用。

## 文章类型 → 组件组合配方

| 文章类型 | 核心组件 | 可选点缀 |
| --- | --- | --- |
| 教程 | 1、2、3 | 4 |

## Markdown → 测试主题映射规则

| Markdown | 组件 |
| --- | --- |
| # 标题 | 2 |
"""

GENERATED_PREVIEW = """<section style="padding:16px"><p><span leaf="">封面标题</span></p></section>
<section style="padding:12px"><h2><span leaf="">章节标题</span></h2></section>
<p style="line-height:1.8"><span leaf="">正文内容</span></p>
<section style="padding:12px;border-left:3px solid #1677ff"><p><span leaf="">引用内容</span></p></section>"""


class GzhThemeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_discovers_the_six_vendored_themes(self) -> None:
        themes = list_themes(self.db)

        self.assertEqual(len(themes), 6)
        self.assertTrue(all(theme.key.startswith("upstream:") for theme in themes))
        self.assertTrue(all(theme.preview_path and theme.preview_path.exists() for theme in themes))
        for theme in themes:
            manifest = build_theme_manifest(theme.source_markdown)
            self.assertGreater(len(manifest.components), 0, theme.name)
            self.assertGreater(len(manifest.recipes), 0, theme.name)

    def test_manifest_extracts_recipes_and_common_components(self) -> None:
        theme = resolve_theme(self.db, "upstream:moyu-green")
        manifest = build_theme_manifest(theme.source_markdown)

        tutorial = next(recipe for recipe in manifest.recipes if "教程" in recipe.article_type)
        component_ids = {component.id for component in manifest.components}
        self.assertIn("7a", tutorial.core_component_ids)
        self.assertIn("8a", tutorial.core_component_ids)
        self.assertIn("common:1a", component_ids)
        self.assertIn("1", manifest.structural_component_ids)
        self.assertIn("13a", manifest.structural_component_ids)

    def test_only_admin_theme_listing_includes_custom_drafts(self) -> None:
        self.db.add_all([
            GzhTheme(
                slug="draft-theme", name="草稿主题", source_markdown="# draft", status=GzhThemeStatus.DRAFT,
            ),
            GzhTheme(
                slug="published-theme", name="发布主题", source_markdown="# published", status=GzhThemeStatus.PUBLISHED,
            ),
            GzhTheme(
                slug="archived-theme", name="归档主题", source_markdown="# archived", status=GzhThemeStatus.ARCHIVED,
            ),
        ])
        self.db.commit()

        user_themes = {theme.name: theme for theme in list_themes(self.db)}
        admin_themes = {theme.name: theme for theme in list_themes(self.db, include_drafts=True)}

        self.assertNotIn("草稿主题", user_themes)
        self.assertEqual(user_themes["发布主题"].status, "published")
        self.assertIn("草稿主题", admin_themes)
        self.assertEqual(admin_themes["草稿主题"].status, "draft")
        self.assertNotIn("归档主题", admin_themes)
        archived = self.db.query(GzhTheme).filter(GzhTheme.slug == "archived-theme").one()
        with self.assertRaisesRegex(GzhThemeError, "不可用"):
            resolve_theme(self.db, f"custom:{archived.id}", include_drafts=True)

    def test_theme_listing_rejects_draft_query_for_regular_users(self) -> None:
        self.db.add(GzhTheme(slug="draft-theme", name="草稿主题", source_markdown="# draft", status=GzhThemeStatus.DRAFT))
        self.db.commit()

        admin_themes = list_gzh_themes(
            include_drafts=True,
            current_user=SimpleNamespace(role=UserRole.ADMIN),
            db=self.db,
        )
        self.assertTrue(any(theme.name == "草稿主题" and theme.status == "draft" for theme in admin_themes))

        with self.assertRaises(HTTPException) as context:
            list_gzh_themes(
                include_drafts=True,
                current_user=SimpleNamespace(role=UserRole.USER),
                db=self.db,
            )
        self.assertEqual(context.exception.status_code, 403)

    def test_strict_validator_accepts_leaf_wrapped_article_content(self) -> None:
        report = validate_gzh_html(
            '<section style="padding:8px"><p><span leaf="">保留正文、链接与图片语义。</span></p></section>'
        )

        self.assertFalse(report["hasError"])
        self.assertEqual(report["leafCount"], 1)

    def test_proposal_requires_the_approved_document_checksum(self) -> None:
        source_html = '<p><span leaf="">原文</span></p>'
        proposal = create_proposal(
            self.db,
            document_id=1,
            session_id=None,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:moyu-green",
            apply_mode="restrained",
            user_instructions="只使用标题与引用样式",
        )
        self.db.commit()

        with self.assertRaisesRegex(GzhThemeError, "文档已发生变化"):
            approve_proposal(self.db, proposal, source_html + "<p>外部修改</p>", 7)
        self.db.rollback()
        proposal = self.db.get(type(proposal), proposal.id)
        self.assertIsNotNone(proposal)
        approved = approve_proposal(self.db, proposal, source_html, 7)
        self.assertEqual(approved.status, GzhThemeProposalStatus.APPROVED)

        consumed = consume_approved_proposal(self.db, approved.id, 1, 7, source_html)
        self.assertEqual(consumed.id, approved.id)
        with self.assertRaisesRegex(GzhThemeError, "文档已发生变化"):
            consume_approved_proposal(self.db, approved.id, 1, 7, source_html + "<p>外部修改</p>")

    def test_reask_recovers_the_bound_approved_theme_proposal(self) -> None:
        source_html = '<p><span leaf="">原文</span></p>'
        proposal = create_proposal(
            self.db,
            document_id=1,
            session_id=3,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:moyu-green",
            apply_mode="full",
            user_instructions="",
        )
        proposal.status = GzhThemeProposalStatus.APPROVED
        message = ChatMessage(
            document_id=1,
            session_id=3,
            created_by_id=7,
            role=MessageRole.USER,
            content="应用已批准的主题排版提案。",
            gzh_theme_proposal_id=proposal.id,
            html_before=source_html,
        )
        self.db.add(message)
        self.db.commit()

        self.assertEqual(
            reask_theme_proposal_id(
                self.db,
                source_message_id=message.id,
                document_id=1,
                session_id=3,
                user_id=7,
            ),
            proposal.id,
        )

    def test_reask_legacy_message_only_recovers_one_matching_approval(self) -> None:
        source_html = '<p><span leaf="">原文</span></p>'
        proposal = create_proposal(
            self.db,
            document_id=1,
            session_id=3,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:moyu-green",
            apply_mode="full",
            user_instructions="",
        )
        proposal.status = GzhThemeProposalStatus.APPROVED
        message = ChatMessage(
            document_id=1,
            session_id=3,
            created_by_id=7,
            role=MessageRole.USER,
            content=f"应用已批准的主题排版提案「{proposal.theme_name}」，请执行。",
            html_before=source_html,
        )
        self.db.add(message)
        self.db.commit()

        self.assertEqual(
            reask_theme_proposal_id(
                self.db,
                source_message_id=message.id,
                document_id=1,
                session_id=3,
                user_id=7,
            ),
            proposal.id,
        )

    def test_reask_legacy_message_refuses_ambiguous_approvals(self) -> None:
        source_html = '<p><span leaf="">原文</span></p>'
        first = create_proposal(
            self.db,
            document_id=1,
            session_id=3,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:moyu-green",
            apply_mode="full",
            user_instructions="",
        )
        second = create_proposal(
            self.db,
            document_id=1,
            session_id=3,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:graphite-minimal",
            apply_mode="full",
            user_instructions="",
        )
        first.status = GzhThemeProposalStatus.APPROVED
        second.status = GzhThemeProposalStatus.APPROVED
        second.theme_name = first.theme_name
        message = ChatMessage(
            document_id=1,
            session_id=3,
            created_by_id=7,
            role=MessageRole.USER,
            content=f"应用已批准的主题排版提案「{first.theme_name}」，请执行。",
            html_before=source_html,
        )
        self.db.add(message)
        self.db.commit()

        self.assertIsNone(
            reask_theme_proposal_id(
                self.db,
                source_message_id=message.id,
                document_id=1,
                session_id=3,
                user_id=7,
            )
        )

    def test_proposal_snapshots_selected_recipe_components(self) -> None:
        source_html = '<section><p><span leaf="">教程步骤与命令</span></p><pre>echo ok</pre></section>'
        proposal = create_proposal(
            self.db,
            document_id=1,
            session_id=None,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:moyu-green",
            apply_mode="full",
            user_instructions="不要使用警告框",
            recipe_id="recipe-01",
            selected_component_ids=["7a", "8a", "8b", "11b"],
        )
        self.db.commit()

        self.assertEqual(proposal.article_type, "教程/操作指南")
        self.assertEqual(proposal.recipe_id, "recipe-01")
        self.assertTrue(proposal.theme_manifest_checksum)
        payload = proposal_theme_payload(proposal, include_html=True)
        self.assertIn("7a", payload["selected_component_ids"])
        self.assertIn("11b", payload["selected_component_ids"])
        self.assertNotIn("10a", payload["selected_component_ids"])
        self.assertTrue(any(item["id"] == "7a" and item.get("html") for item in payload["components"]))

    def test_proposal_rejects_components_outside_the_selected_recipe(self) -> None:
        with self.assertRaisesRegex(GzhThemeError, "不属于当前文章类型配方"):
            create_proposal(
                self.db,
                document_id=1,
                session_id=None,
                user_id=7,
                current_html='<p><span leaf="">原文</span></p>',
                theme_key="upstream:moyu-green",
                apply_mode="full",
                user_instructions="",
                recipe_id="recipe-01",
                selected_component_ids=["9a"],
            )

    def test_auto_recipe_respects_the_component_set_already_confirmed_in_the_gallery(self) -> None:
        # The document heuristic would normally prefer a data-report recipe,
        # but the user has seen and confirmed the tutorial combination.
        proposal = create_proposal(
            self.db,
            document_id=1,
            session_id=None,
            user_id=7,
            current_html='<table><tr><td>2026</td><td>100</td></tr></table>',
            theme_key="upstream:moyu-green",
            apply_mode="full",
            user_instructions="",
            recipe_id="auto",
            selected_component_ids=["7a", "8a", "8b", "10a", "10b", "11b"],
        )

        self.assertEqual(proposal.recipe_id, "recipe-01")
        self.assertEqual(proposal.article_type, "教程/操作指南")

    def test_latest_applied_proposal_is_retained_as_a_theme_reference(self) -> None:
        source_html = '<p><span leaf="">原文</span></p>'
        older = create_proposal(
            self.db,
            document_id=1,
            session_id=3,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:moyu-green",
            apply_mode="restrained",
            user_instructions="旧要求",
        )
        newer = create_proposal(
            self.db,
            document_id=1,
            session_id=4,
            user_id=7,
            current_html=source_html,
            theme_key="upstream:graphite-minimal",
            apply_mode="key_components",
            user_instructions="新要求",
        )
        now = datetime.now(timezone.utc)
        older.status = GzhThemeProposalStatus.APPLIED
        older.applied_at = now - timedelta(minutes=1)
        newer.status = GzhThemeProposalStatus.APPLIED
        newer.applied_at = now
        self.db.commit()

        reference = latest_applied_theme_proposal(self.db, document_id=1)

        self.assertIsNotNone(reference)
        self.assertEqual(reference.id, newer.id)
        self.assertEqual(reference.user_instructions, "新要求")
        self.assertEqual(reference.status, GzhThemeProposalStatus.APPLIED)

    def test_custom_component_lint_rejects_unsupported_markup(self) -> None:
        findings = lint_theme_source(
            "# 自定义主题\n\n```html\n<div class=\"card\"><p>不兼容组件</p></div>\n```\n"
        )

        errors = [item["message"] for item in findings if item["level"] == "ERROR"]
        self.assertTrue(any("<div>" in message for message in errors))
        self.assertTrue(any("class" in message for message in errors))

    def test_custom_component_lint_rejects_external_font_in_html_components(self) -> None:
        findings = lint_theme_source(
            "# 自定义主题\n\n```html\n<section style=\"font-family:bad;src:url(https://example.test/theme.woff2)\"><span leaf=\"\">文字</span></section>\n```\n"
        )

        errors = [item["message"] for item in findings if item["level"] == "ERROR"]
        self.assertTrue(any("外部字体" in message for message in errors))

    def test_generated_package_requires_standard_sections_and_strict_preview(self) -> None:
        validated = validate_generated_package({
            "source_markdown": GENERATED_SOURCE,
            "preview_html": GENERATED_PREVIEW,
        })

        self.assertEqual(len(validated["manifest"]["recipes"]), 1)
        self.assertGreaterEqual(len(validated["manifest"]["components"]), 4)
        with self.assertRaisesRegex(GzhThemeGenerationError, "预览"):
            validate_generated_package({"source_markdown": GENERATED_SOURCE, "preview_html": "<script>alert(1)</script>"})

    def test_generation_saves_draft_then_publishes_new_version_without_changing_old_snapshot(self) -> None:
        generation = GzhThemeGeneration(
            id="generation-1",
            model_id=1,
            user_id=7,
            name_hint="版本化主题",
            slug_hint="versioned-theme",
            accent_color="#1677ff",
            scenarios_json='["教程"]',
            brief="克制技术教程主题",
            output_json=(
                '{"name":"版本化主题","slug":"versioned-theme","description":"教程","scenarios":["教程"],'
                '"accent_color":"#1677ff","source_markdown":' + __import__("json").dumps(GENERATED_SOURCE, ensure_ascii=False) + ','
                '"preview_html":' + __import__("json").dumps(GENERATED_PREVIEW, ensure_ascii=False) + '}'
            ),
            status=GzhThemeGenerationStatus.SUCCEEDED,
        )
        self.db.add(generation)
        self.db.flush()

        theme, draft = save_generation_as_draft(self.db, generation)
        self.assertEqual(draft.version, 1)
        self.assertEqual(theme.status, GzhThemeStatus.DRAFT)
        old_source = draft.source_markdown

        publish_theme_version(self.db, theme, draft)
        self.db.commit()
        self.assertEqual(theme.status, GzhThemeStatus.PUBLISHED)
        self.assertEqual(theme.active_version_id, draft.id)
        self.assertEqual(old_source, draft.source_markdown)


if __name__ == "__main__":
    unittest.main()
