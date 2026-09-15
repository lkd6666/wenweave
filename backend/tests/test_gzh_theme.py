import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.gzh_themes import _generation_read, list_gzh_themes
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
    THEME_COMPONENT_IDS,
    _parse_json_object,
    build_standard_theme_package,
    publish_theme_version,
    run_generation,
    save_generation_as_draft,
    validate_component_batch,
    validate_generated_package,
    validate_theme_blueprint,
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


def standard_blueprint() -> dict:
    component_ids = list(THEME_COMPONENT_IDS)
    return {
        "name": "标准测试主题",
        "slug": "standard-test-theme",
        "description": "用于验证完整组件覆盖的标准主题。",
        "scenarios": ["教程", "复盘", "品牌故事"],
        "accent_color": "#1677ff",
        "design_tokens": [
            {"name": "主色", "value": "#1677ff"},
            {"name": "辅助色", "value": "#e6f4ff"},
            {"name": "正文色", "value": "#1f2937"},
            {"name": "弱文本", "value": "#667085"},
            {"name": "背景色", "value": "#ffffff"},
            {"name": "边框色", "value": "#d0d5dd"},
        ],
        "components": [{"id": component_id, "name": f"测试组件 {component_id}"} for component_id in component_ids],
        "recipes": [
            {
                "article_type": article_type,
                "core_component_ids": ["1", "3", "5", "24"],
                "decorative_component_ids": decorative,
            }
            for article_type, decorative in (
                ("教程", ["12", "14", "16"]),
                ("复盘", ["7", "15", "18"]),
                ("品牌故事", ["2", "19", "23"]),
            )
        ],
        "markdown_mappings": [
            {"markdown": "# 一级标题", "component_id": "3"},
            {"markdown": "## 二级标题", "component_id": "4"},
            {"markdown": "正文", "component_id": "5"},
            {"markdown": "> 引用", "component_id": "7"},
            {"markdown": "```代码```", "component_id": "16"},
        ],
    }


def standard_component_payload(component_ids: tuple[str, ...] | list[str]) -> dict:
    return {
        "components": [
            {
                "id": component_id,
                "html": (
                    f'<section style="margin:12px 0;padding:12px;border:1px solid #d0d5dd">'
                    f'<p style="margin:0"><span leaf="">组件 {component_id} 展示文案</span></p></section>'
                ),
            }
            for component_id in component_ids
        ]
    }


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

    def test_strict_json_parser_rejects_explanatory_text(self) -> None:
        self.assertEqual(_parse_json_object('```json\n{"ok":true}\n```', "测试结果"), {"ok": True})
        with self.assertRaisesRegex(GzhThemeGenerationError, "不是有效 JSON"):
            _parse_json_object('下面是结果：{"ok":true}', "测试结果")

    def test_generation_api_exposes_durable_progress(self) -> None:
        generation = GzhThemeGeneration(
            id="generation-progress",
            model_id=1,
            user_id=7,
            brief="蓝色教程主题",
            status=GzhThemeGenerationStatus.RUNNING,
            progress_stage="generating_components",
            progress_current=4,
            progress_total=10,
            progress_message="正在生成组件第 4/8 批",
        )
        self.db.add(generation)
        self.db.flush()

        payload = _generation_read(generation)

        self.assertEqual(payload.progress.stage, "generating_components")
        self.assertEqual(payload.progress.current, 4)
        self.assertEqual(payload.progress.total, 10)
        self.assertEqual(payload.progress.message, "正在生成组件第 4/8 批")

    def test_standard_theme_package_requires_all_24_component_slots(self) -> None:
        blueprint = validate_theme_blueprint(standard_blueprint())
        components = {}
        for start in range(0, len(THEME_COMPONENT_IDS), 3):
            component_ids = THEME_COMPONENT_IDS[start:start + 3]
            components.update(validate_component_batch(standard_component_payload(component_ids), component_ids))

        package = build_standard_theme_package(blueprint, components)
        validated = validate_generated_package(package, require_standard=True)

        theme_components = [item for item in validated["manifest"]["components"] if item["source"] == "theme"]
        self.assertEqual([item["id"] for item in theme_components], list(THEME_COMPONENT_IDS))
        self.assertEqual(len(validated["manifest"]["recipes"]), 3)

        del components["24"]
        with self.assertRaisesRegex(GzhThemeGenerationError, "组件不完整"):
            build_standard_theme_package(blueprint, components)

    def test_component_batch_rejects_unwrapped_text(self) -> None:
        component_ids = THEME_COMPONENT_IDS[:3]
        payload = standard_component_payload(component_ids)
        payload["components"][1]["html"] = '<section style="padding:12px"><p>未包装文本</p></section>'

        with self.assertRaisesRegex(GzhThemeGenerationError, "严格检查"):
            validate_component_batch(payload, component_ids)

    def test_generation_repairs_only_the_failed_component_batch(self) -> None:
        run_db = Session(self.engine)
        generation = GzhThemeGeneration(
            id="generation-repair-batch",
            model_id=1,
            user_id=7,
            brief="蓝色教程主题",
            status=GzhThemeGenerationStatus.PENDING,
        )
        run_db.add(generation)
        run_db.commit()
        generation_id = generation.id

        blueprint = standard_blueprint()
        first_batch_invalid = standard_component_payload(THEME_COMPONENT_IDS[:3])
        first_batch_invalid["components"][0]["html"] = (
            '<div style="margin:12px 0"><p><span leaf="">错误容器</span></p></div>'
        )
        responses = [blueprint, first_batch_invalid]
        for start in range(0, len(THEME_COMPONENT_IDS), 3):
            responses.append(standard_component_payload(THEME_COMPONENT_IDS[start:start + 3]))
        ask_model = AsyncMock(side_effect=responses)

        with patch("app.services.gzh_theme_generation.SessionLocal", return_value=run_db), patch(
            "app.services.gzh_theme_generation._ask_json_prompt", ask_model
        ):
            asyncio.run(run_generation(generation_id))

        check_db = Session(self.engine)
        completed = check_db.get(GzhThemeGeneration, generation_id)
        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, GzhThemeGenerationStatus.SUCCEEDED)
        self.assertEqual(completed.progress_stage, "succeeded")
        self.assertEqual(completed.progress_current, completed.progress_total)
        self.assertEqual(ask_model.await_count, 1 + 1 + 1 + (len(THEME_COMPONENT_IDS) // 3 - 1))
        repair_prompt = ask_model.await_args_list[2].args[2]
        self.assertIn("<validation_feedback>", repair_prompt)
        self.assertIn("组件 1 严格检查未通过", repair_prompt)
        self.assertIn("绝不能使用 <div>", repair_prompt)
        check_db.close()

    def test_generation_reconnects_once_after_a_transient_model_error(self) -> None:
        from app.services import gzh_theme_generation as generation_service

        run_db = Session(self.engine)
        generation = GzhThemeGeneration(
            id="generation-reconnect",
            model_id=1,
            user_id=7,
            brief="蓝色教程主题",
            status=GzhThemeGenerationStatus.PENDING,
        )
        run_db.add(generation)
        run_db.commit()
        generation_id = generation.id

        responses = [standard_blueprint(), ConnectionError("Connection error.")]
        for start in range(0, len(THEME_COMPONENT_IDS), 3):
            responses.append(standard_component_payload(THEME_COMPONENT_IDS[start:start + 3]))
        ask_model = AsyncMock(side_effect=responses)
        progress_stages: list[str] = []
        original_set_progress = generation_service._set_progress

        def record_progress(*args, **kwargs):
            progress_stages.append(kwargs["stage"])
            return original_set_progress(*args, **kwargs)

        with patch("app.services.gzh_theme_generation.SessionLocal", return_value=run_db), patch(
            "app.services.gzh_theme_generation._ask_json_prompt", ask_model
        ), patch("app.services.gzh_theme_generation._set_progress", side_effect=record_progress), patch(
            "app.services.gzh_theme_generation.asyncio.sleep", AsyncMock()
        ):
            asyncio.run(run_generation(generation_id))

        check_db = Session(self.engine)
        completed = check_db.get(GzhThemeGeneration, generation_id)
        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, GzhThemeGenerationStatus.SUCCEEDED)
        self.assertIn("reconnecting", progress_stages)
        self.assertEqual(ask_model.await_count, 1 + 1 + (len(THEME_COMPONENT_IDS) // 3))
        check_db.close()

    def test_generation_stops_after_cancellation_between_stages(self) -> None:
        run_db = Session(self.engine)
        generation = GzhThemeGeneration(
            id="generation-cancel-stage",
            model_id=1,
            user_id=7,
            brief="蓝色教程主题",
            status=GzhThemeGenerationStatus.PENDING,
        )
        run_db.add(generation)
        run_db.commit()
        generation_id = generation.id

        async def cancel_after_blueprint(*_args, **_kwargs):
            other_session = Session(self.engine)
            row = other_session.get(GzhThemeGeneration, generation_id)
            row.cancel_requested = True
            other_session.commit()
            other_session.close()
            return standard_blueprint()

        with patch("app.services.gzh_theme_generation.SessionLocal", return_value=run_db), patch(
            "app.services.gzh_theme_generation._ask_json_prompt", AsyncMock(side_effect=cancel_after_blueprint)
        ):
            asyncio.run(run_generation(generation_id))

        check_db = Session(self.engine)
        cancelled = check_db.get(GzhThemeGeneration, generation_id)
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, GzhThemeGenerationStatus.CANCELLED)
        self.assertEqual(cancelled.progress_stage, "cancelled")
        check_db.close()

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
