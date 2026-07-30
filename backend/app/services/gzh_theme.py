"""Adapter around the vendored gzh-design-skill assets.

The upstream repository is deliberately read-only. Application-created themes
live in the database and expose the same Markdown component-library shape.
"""
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage, MessageRole
from app.models.gzh_theme import GzhTheme, GzhThemeStatus, GzhThemeVersion, GzhThemeVersionStatus
from app.models.gzh_theme_proposal import GzhThemeProposal, GzhThemeProposalStatus
from app.services.document_versions import content_checksum


REPO_ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_ROOT = REPO_ROOT / "_third_party" / "gzh-design-skill"
THEME_INDEX = UPSTREAM_ROOT / "references" / "theme-index.md"
COMMON_COMPONENTS = UPSTREAM_ROOT / "references" / "common-components.md"
THEME_GENERATOR = UPSTREAM_ROOT / "references" / "theme-generator.md"
PREVIEW_DIR = UPSTREAM_ROOT / "docs" / "gallery"
PROPOSAL_TTL = timedelta(minutes=30)
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}")
_HTML_FENCE = re.compile(r"```html[ \t]*\r?\n(.*?)```", re.IGNORECASE | re.DOTALL)
_UNSUPPORTED_COMPONENT_TAG = re.compile(
    r"<\s*/?\s*(?:form|input|button|textarea|select|video|audio|canvas|svg)\b", re.IGNORECASE
)
_UNSUPPORTED_COMPONENT_CSS = re.compile(r"@font-face|expression\s*\(", re.IGNORECASE)
_COMPONENT_H2 = re.compile(r"^##\s+组件\s*(\d+[a-z]?)\s*(.*)$", re.IGNORECASE)
_COMPONENT_H3 = re.compile(r"^###\s+(\d+[a-z]?)\.\s*(.*)$", re.IGNORECASE)
_GENERIC_H2 = re.compile(r"^##\s+(.+?)\s*$")
_COMPONENT_ID_REFERENCE = re.compile(r"(?<![\w-])(\d+[a-z]?)(?![\w-])", re.IGNORECASE)
_TOKEN_LINE = re.compile(r"^\s*(?:[-*]\s*)?([^:：|`]{1,40})\s*[:：|]\s*`?([^`|\n]{1,80})`?\s*$")


@dataclass(frozen=True)
class ThemeComponent:
    id: str
    name: str
    category: str
    source: str
    html: str


@dataclass(frozen=True)
class ThemeRecipe:
    id: str
    article_type: str
    core_component_ids: tuple[str, ...]
    decorative_component_ids: tuple[str, ...]


@dataclass(frozen=True)
class ThemeManifest:
    schema_version: int
    source_checksum: str
    design_tokens: tuple[dict[str, str], ...]
    components: tuple[ThemeComponent, ...]
    recipes: tuple[ThemeRecipe, ...]
    structural_component_ids: tuple[str, ...]


class GzhThemeError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedGzhTheme:
    id: int | None
    key: str
    name: str
    description: str
    scenarios: list[str]
    accent_color: str
    source_markdown: str
    preview_path: Path | None
    is_builtin: bool
    status: str
    version_id: int | None = None
    version: int | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _theme_index_rows() -> list[tuple[str, str, str, str]]:
    """Read the upstream Markdown table without assuming its presentation cells.

    The color column intentionally combines a backticked hex value with a
    human-readable color name, so a generic backtick-based regex would skip
    every actual theme row.
    """
    rows: list[tuple[str, str, str, str]] = []
    for line in THEME_INDEX.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
        if len(cells) < 4:
            continue
        name, color_cell, scenarios, source_cell = cells[:4]
        source_file = source_cell.strip().strip("`")
        if not source_file.startswith("references/theme-"):
            continue
        color_match = _HEX_COLOR.search(color_cell)
        if not color_match:
            continue
        rows.append((name, color_match.group(0), scenarios, source_file))
    return rows


@lru_cache(maxsize=1)
def _builtin_themes() -> dict[str, ResolvedGzhTheme]:
    if not THEME_INDEX.exists():
        raise GzhThemeError("未找到上游 gzh-design-skill 主题索引，请确认 _third_party/gzh-design-skill 已随部署提供")
    result: dict[str, ResolvedGzhTheme] = {}
    for name, color, scenarios, source_file in _theme_index_rows():
        source_rel = source_file.strip().replace("\\", "/")
        if not source_rel.startswith("references/theme-"):
            continue
        theme_path = UPSTREAM_ROOT / source_rel
        if not theme_path.exists():
            continue
        slug = theme_path.stem.removeprefix("theme-")
        preview = PREVIEW_DIR / f"{slug}.html"
        result[f"upstream:{slug}"] = ResolvedGzhTheme(
            id=None,
            key=f"upstream:{slug}",
            name=name.strip(),
            description=scenarios.strip(),
            scenarios=[item.strip() for item in re.split(r"、|，|,", scenarios) if item.strip()],
            accent_color=color.strip(),
            source_markdown=theme_path.read_text(encoding="utf-8"),
            preview_path=preview if preview.exists() else None,
            is_builtin=True,
            status=GzhThemeStatus.PUBLISHED.value,
        )
    if not result:
        raise GzhThemeError("上游主题索引中没有可读取的主题组件库")
    return result


def clear_builtin_theme_cache() -> None:
    _builtin_themes.cache_clear()


def active_theme_version(db: Session, theme: GzhTheme) -> GzhThemeVersion | None:
    """Find the version selected for normal gallery resolution.

    A no-version fallback is deliberate for in-memory tests and for a process
    which starts before the one-time data migration has materialized v1.
    """
    if theme.active_version_id:
        version = db.get(GzhThemeVersion, theme.active_version_id)
        if version and version.theme_id == theme.id:
            return version
    return (
        db.query(GzhThemeVersion)
        .filter(GzhThemeVersion.theme_id == theme.id)
        .order_by(GzhThemeVersion.version.desc())
        .first()
    )


def _resolved_custom_theme(db: Session, item: GzhTheme) -> ResolvedGzhTheme:
    version = active_theme_version(db, item)
    return ResolvedGzhTheme(
        id=item.id,
        key=f"custom:{item.id}",
        name=item.name,
        description=item.description,
        scenarios=[part.strip() for part in item.scenarios.split("\n") if part.strip()],
        accent_color=item.accent_color,
        source_markdown=version.source_markdown if version else item.source_markdown,
        preview_path=None,
        is_builtin=False,
        status=item.status.value,
        version_id=version.id if version else None,
        version=version.version if version else None,
    )


def list_themes(db: Session, include_drafts: bool = False) -> list[ResolvedGzhTheme]:
    themes = list(_builtin_themes().values())
    query = db.query(GzhTheme)
    if not include_drafts:
        query = query.filter(GzhTheme.status == GzhThemeStatus.PUBLISHED)
    else:
        query = query.filter(GzhTheme.status.in_((GzhThemeStatus.DRAFT, GzhThemeStatus.PUBLISHED)))
    for item in query.order_by(GzhTheme.updated_at.desc()).all():
        themes.append(_resolved_custom_theme(db, item))
    return themes


def resolve_theme(db: Session, theme_key: str, include_drafts: bool = False) -> ResolvedGzhTheme:
    if theme_key.startswith("upstream:"):
        theme = _builtin_themes().get(theme_key)
        if theme:
            return theme
    elif theme_key.startswith("custom:"):
        raw_id = theme_key.removeprefix("custom:")
        if raw_id.isdigit():
            theme = db.get(GzhTheme, int(raw_id))
            visible = theme and (
                theme.status == GzhThemeStatus.PUBLISHED
                or (include_drafts and theme.status == GzhThemeStatus.DRAFT)
            )
            if visible:
                return _resolved_custom_theme(db, theme)
    raise GzhThemeError("主题不存在、尚未发布或不可用")


def preview_html(db: Session, theme_key: str, include_drafts: bool = False) -> str:
    theme = resolve_theme(db, theme_key, include_drafts=include_drafts)
    if theme.preview_path:
        return theme.preview_path.read_text(encoding="utf-8")
    if theme_key.startswith("custom:"):
        theme_id = int(theme_key.removeprefix("custom:"))
        record = db.get(GzhTheme, theme_id)
        version = active_theme_version(db, record) if record else None
        if version and version.preview_html:
            return version.preview_html
        if record and record.preview_html:
            return record.preview_html
    # A source-only draft can still show a safe, compact metadata preview.
    return (
        '<section style="padding:28px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">'
        f'<p style="margin:0 0 8px;color:{theme.accent_color};font-size:12px;font-weight:700;">CUSTOM THEME</p>'
        f'<h2 style="margin:0;color:#1f2937;font-size:24px;">{theme.name}</h2>'
        f'<p style="color:#667085;line-height:1.8;">{theme.description or "已保存主题组件库，发布后可用于文章排版。"}</p>'
        '</section>'
    )


def common_components() -> str:
    if not COMMON_COMPONENTS.exists():
        raise GzhThemeError("未找到上游通用组件库")
    return COMMON_COMPONENTS.read_text(encoding="utf-8")


def _heading_blocks(source: str, heading_pattern: re.Pattern[str]) -> list[tuple[str, str, str]]:
    """Return Markdown sections keyed by a component heading.

    Upstream themes use level-two headings for whole components and level-three
    headings for variants.  The common library only has level-three variants.
    Keeping the original HTML fence instead of regenerating it makes the
    manifest an index over the vendor asset rather than a second theme format.
    """
    lines = source.splitlines()
    matches: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = heading_pattern.match(line)
        if match:
            matches.append((index, match))
    blocks: list[tuple[str, str, str]] = []
    for offset, (start, match) in enumerate(matches):
        end = matches[offset + 1][0] if offset + 1 < len(matches) else len(lines)
        component_id = match.group(1).lower()
        name = match.group(2).strip() or component_id
        html = "\n\n".join(_HTML_FENCE.findall("\n".join(lines[start + 1:end]))).strip()
        if html:
            blocks.append((component_id, name, html))
    return blocks


def _theme_components(source: str) -> list[ThemeComponent]:
    lines = source.splitlines()
    h2_matches: list[tuple[int, re.Match[str]]] = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _COMPONENT_H2.match(line))
    ]
    components: list[ThemeComponent] = []
    for offset, (start, match) in enumerate(h2_matches):
        end = h2_matches[offset + 1][0] if offset + 1 < len(h2_matches) else len(lines)
        component_id = match.group(1).lower()
        name = match.group(2).strip() or component_id
        section = "\n".join(lines[start + 1:end])
        # A group such as "组件 6 行内样式" is represented by its variants,
        # not by a duplicate parent component.
        has_child_components = any(_COMPONENT_H3.match(line) for line in section.splitlines())
        if not has_child_components:
            html = "\n\n".join(_HTML_FENCE.findall(section)).strip()
            if html:
                components.append(ThemeComponent(component_id, name, "主题组件", "theme", html))
    for component_id, name, html in _heading_blocks(source, _COMPONENT_H3):
        components.append(ThemeComponent(component_id, name, "主题组件", "theme", html))
    return components


def _common_theme_components() -> list[ThemeComponent]:
    return [
        ThemeComponent(f"common:{component_id}", name, "通用组件", "common", html)
        for component_id, name, html in _heading_blocks(common_components(), _COMPONENT_H3)
    ]


def _design_tokens(source: str) -> list[dict[str, str]]:
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("## 设计变量")), None)
    if start is None:
        return []
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    tokens: list[dict[str, str]] = []
    for line in lines[start + 1:end]:
        match = _TOKEN_LINE.match(line)
        if not match:
            continue
        name, value = match.groups()
        name = name.strip(" -`|")
        value = value.strip(" -`|")
        if name and value and len(tokens) < 24:
            tokens.append({"name": name, "value": value})
    return tokens


def _section_text(source: str, heading_prefix: str) -> str:
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(heading_prefix)), None)
    if start is None:
        return ""
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1:end]).strip()


def _component_aliases(components: list[ThemeComponent]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for component in components:
        for candidate in re.findall(r"[a-z][a-z0-9-]+", component.name.lower()):
            aliases.setdefault(candidate, component.id)
    return aliases


def _component_ids_from_recipe(text: str, ids: set[str], aliases: dict[str, str]) -> list[str]:
    selected: list[str] = []

    def add(component_id: str) -> None:
        if component_id in ids and component_id not in selected:
            selected.append(component_id)

    for token in _COMPONENT_ID_REFERENCE.findall(text.lower()):
        add(token if token in ids else f"common:{token}")
    for alias, component_id in aliases.items():
        if re.search(rf"(?<![a-z0-9-]){re.escape(alias)}(?![a-z0-9-])", text.lower()):
            add(component_id)
    return selected


def _recipe_rows(source: str, components: list[ThemeComponent]) -> list[ThemeRecipe]:
    table = _section_text(source, "## 文章类型")
    if not table:
        return []
    ids = {component.id for component in components}
    aliases = _component_aliases(components)
    recipes: list[ThemeRecipe] = []
    for line in table.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
        if len(cells) < 3 or cells[0] in {"文章类型", "------"} or set(cells[0]) <= {"-", " "}:
            continue
        core = _component_ids_from_recipe(cells[1], ids, aliases)
        decorative = _component_ids_from_recipe(cells[2], ids, aliases)
        recipes.append(
            ThemeRecipe(
                id=f"recipe-{len(recipes) + 1:02d}",
                article_type=cells[0],
                core_component_ids=tuple(core),
                decorative_component_ids=tuple(item for item in decorative if item not in core),
            )
        )
    return recipes


def build_theme_manifest(source: str) -> ThemeManifest:
    """Derive a stable, JSON-safe theme manifest from the upstream Markdown."""
    theme_components = _theme_components(source)
    all_components = theme_components + _common_theme_components()
    component_ids = {component.id for component in all_components}
    structural = tuple(item for item in ("1", "2", "3", "4", "5", "13a") if item in component_ids)
    recipes = _recipe_rows(source, all_components)
    if not recipes:
        # Custom drafts should normally provide an upstream-compatible recipe
        # table.  This fallback keeps legacy source-only drafts usable while
        # still constraining selection to discovered components.
        available = [component.id for component in theme_components[:3]]
        recipes = [ThemeRecipe("recipe-01", "通用文章", tuple(available), tuple())]
    return ThemeManifest(
        schema_version=1,
        source_checksum=content_checksum(source),
        design_tokens=tuple(_design_tokens(source)),
        components=tuple(all_components),
        recipes=tuple(recipes),
        structural_component_ids=structural,
    )


def manifest_payload(manifest: ThemeManifest, *, include_html: bool = False) -> dict[str, Any]:
    components = []
    for component in manifest.components:
        item: dict[str, Any] = {
            "id": component.id,
            "name": component.name,
            "category": component.category,
            "source": component.source,
        }
        if include_html:
            item["html"] = component.html
        components.append(item)
    return {
        "schema_version": manifest.schema_version,
        "source_checksum": manifest.source_checksum,
        "design_tokens": list(manifest.design_tokens),
        "components": components,
        "recipes": [
            {
                "id": recipe.id,
                "article_type": recipe.article_type,
                "core_component_ids": list(recipe.core_component_ids),
                "decorative_component_ids": list(recipe.decorative_component_ids),
            }
            for recipe in manifest.recipes
        ],
        "structural_component_ids": list(manifest.structural_component_ids),
        "recommended_recipe_id": manifest.recipes[0].id if manifest.recipes else "",
    }


def theme_manifest(db: Session, theme_key: str, include_drafts: bool = False) -> dict[str, Any]:
    theme = resolve_theme(db, theme_key, include_drafts=include_drafts)
    return manifest_payload(build_theme_manifest(theme.source_markdown))


def _snapshot_manifest(source: str) -> dict[str, Any]:
    return manifest_payload(build_theme_manifest(source))


def _recommend_recipe(recipes: list[dict[str, Any]], current_html: str) -> dict[str, Any]:
    if not recipes:
        raise GzhThemeError("主题组件库没有可用的文章类型配方")
    plain = re.sub(r"<[^>]+>", " ", current_html).lower()
    if "<table" in current_html.lower() or sum(character.isdigit() for character in plain) >= 16:
        hints = ("数据", "报告", "复盘")
    elif "<pre" in current_html.lower() or "<code" in current_html.lower() or any(item in plain for item in ("步骤", "教程", "如何")):
        hints = ("教程", "操作", "案例")
    elif current_html.lower().count("<li") >= 3 or any(item in plain for item in ("清单", "盘点", "工具")):
        hints = ("盘点", "清单")
    else:
        hints = ()
    for recipe in recipes:
        if any(hint in str(recipe["article_type"]) for hint in hints):
            return recipe
    return recipes[0]


def _choose_recipe(
    manifest: dict[str, Any],
    *,
    recipe_id: str,
    article_type: str,
    current_html: str,
    selected_component_ids: list[str] | None = None,
    structural_component_ids: list[str] | None = None,
) -> dict[str, Any]:
    recipes = [item for item in manifest.get("recipes", []) if isinstance(item, dict)]
    if recipe_id and recipe_id != "auto":
        chosen = next((item for item in recipes if item.get("id") == recipe_id), None)
        if not chosen:
            raise GzhThemeError("所选文章类型配方已不可用，请重新选择")
        return chosen
    # Older gallery clients submitted `auto` together with the component set
    # rendered in the UI.  Prefer that explicit selection over a second,
    # potentially different document heuristic so the confirmation remains
    # deterministic during a rolling frontend deployment.
    requested = set(selected_component_ids or []) - set(structural_component_ids or [])
    if requested:
        candidates = []
        for item in recipes:
            allowed = set(item.get("core_component_ids", [])) | set(item.get("decorative_component_ids", []))
            core = set(item.get("core_component_ids", []))
            if requested <= allowed and core <= requested:
                candidates.append(item)
        if len(candidates) == 1:
            return candidates[0]
    if article_type and article_type != "auto":
        chosen = next((item for item in recipes if item.get("article_type") == article_type), None)
        if chosen:
            return chosen
        raise GzhThemeError("所选文章类型配方已不可用，请重新选择")
    return _recommend_recipe(recipes, current_html)


def _choose_components(recipe: dict[str, Any], structural: list[str], requested: list[str] | None) -> list[str]:
    core = [str(item) for item in recipe.get("core_component_ids", [])]
    decorative = [str(item) for item in recipe.get("decorative_component_ids", [])]
    allowed = set(core + decorative)
    if requested:
        unknown = [item for item in requested if item not in allowed]
        if unknown:
            raise GzhThemeError("组件选择不属于当前文章类型配方，请刷新后重试")
        chosen = core + [item for item in decorative if item in requested]
    else:
        chosen = core + decorative
    result: list[str] = []
    for component_id in structural + chosen:
        if component_id not in result:
            result.append(component_id)
    return result


def proposal_theme_payload(proposal: GzhThemeProposal, *, include_html: bool = False) -> dict[str, Any]:
    try:
        manifest = json.loads(proposal.theme_manifest_json or "{}")
    except json.JSONDecodeError:
        manifest = _snapshot_manifest(proposal.theme_markdown)
    if not manifest.get("components"):
        manifest = _snapshot_manifest(proposal.theme_markdown)
    selected = json.loads(proposal.selected_component_ids_json or "[]")
    selected = [str(item) for item in selected if isinstance(item, str)]
    component_by_id = {component.id: component for component in build_theme_manifest(proposal.theme_markdown).components}
    scoped_components = []
    for component_id in selected:
        component = component_by_id.get(component_id)
        if not component:
            continue
        item = {
            "id": component.id,
            "name": component.name,
            "category": component.category,
            "source": component.source,
        }
        if include_html:
            item["html"] = component.html
        scoped_components.append(item)
    return {
        "manifest": manifest,
        "recipe_id": proposal.recipe_id,
        "article_type": proposal.article_type,
        "selected_component_ids": selected,
        "components": scoped_components,
    }


def theme_generator_guide() -> str:
    if not THEME_GENERATOR.exists():
        raise GzhThemeError("未找到上游主题生成规范")
    return THEME_GENERATOR.read_text(encoding="utf-8")


def create_proposal(
    db: Session,
    *,
    document_id: int,
    session_id: int | None,
    user_id: int,
    current_html: str,
    theme_key: str,
    apply_mode: str,
    user_instructions: str,
    article_type: str = "auto",
    recipe_id: str = "",
    selected_component_ids: list[str] | None = None,
) -> GzhThemeProposal:
    theme = resolve_theme(db, theme_key)
    manifest = _snapshot_manifest(theme.source_markdown)
    recipe = _choose_recipe(
        manifest,
        recipe_id=recipe_id.strip(),
        article_type=article_type.strip(),
        current_html=current_html,
        selected_component_ids=selected_component_ids,
        structural_component_ids=[str(item) for item in manifest.get("structural_component_ids", [])],
    )
    selected = _choose_components(
        recipe,
        [str(item) for item in manifest.get("structural_component_ids", [])],
        selected_component_ids,
    )
    proposal = GzhThemeProposal(
        id=__import__("uuid").uuid4().hex,
        document_id=document_id,
        session_id=session_id,
        user_id=user_id,
        theme_key=theme.key,
        theme_name=theme.name,
        theme_markdown=theme.source_markdown,
        theme_manifest_json=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        theme_manifest_checksum=str(manifest["source_checksum"]),
        article_type=str(recipe["article_type"]),
        recipe_id=str(recipe["id"]),
        selected_component_ids_json=json.dumps(selected, ensure_ascii=False),
        apply_mode=apply_mode,
        user_instructions=user_instructions.strip(),
        base_checksum=content_checksum(current_html),
        status=GzhThemeProposalStatus.PENDING,
        expires_at=_utcnow() + PROPOSAL_TTL,
    )
    db.add(proposal)
    db.flush()
    return proposal


def approve_proposal(db: Session, proposal: GzhThemeProposal, current_html: str, user_id: int) -> GzhThemeProposal:
    if proposal.user_id != user_id:
        raise GzhThemeError("无权确认该主题提案")
    if proposal.status != GzhThemeProposalStatus.PENDING:
        raise GzhThemeError("该主题提案已不在待确认状态")
    if _normalise_datetime(proposal.expires_at) <= _utcnow():
        proposal.status = GzhThemeProposalStatus.EXPIRED
        raise GzhThemeError("主题提案已过期，请重新选择主题")
    if proposal.base_checksum != content_checksum(current_html):
        raise GzhThemeError("文档已发生变化，请刷新后重新选择主题")
    proposal.status = GzhThemeProposalStatus.APPROVED
    return proposal


def consume_approved_proposal(db: Session, proposal_id: str, document_id: int, user_id: int, current_html: str) -> GzhThemeProposal:
    proposal = db.get(GzhThemeProposal, proposal_id)
    if not proposal or proposal.document_id != document_id or proposal.user_id != user_id:
        raise GzhThemeError("主题提案不存在或无权使用")
    if proposal.status != GzhThemeProposalStatus.APPROVED:
        raise GzhThemeError("主题提案尚未确认或已被使用")
    if _normalise_datetime(proposal.expires_at) <= _utcnow():
        proposal.status = GzhThemeProposalStatus.EXPIRED
        raise GzhThemeError("主题提案已过期，请重新选择主题")
    if proposal.base_checksum != content_checksum(current_html):
        raise GzhThemeError("文档已发生变化，请重新选择主题")
    return proposal


def reask_theme_proposal_id(
    db: Session,
    *,
    source_message_id: int,
    document_id: int,
    session_id: int,
    user_id: int,
) -> str | None:
    """Recover the proposal bound to a historical theme-application request.

    New messages retain the exact proposal id.  The narrow name/checksum
    fallback only supports messages created before that field existed; it
    refuses ambiguous matches instead of guessing which approval to consume.
    """
    source = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == source_message_id,
            ChatMessage.document_id == document_id,
            ChatMessage.session_id == session_id,
            ChatMessage.role == MessageRole.USER,
        )
        .one_or_none()
    )
    if source is None:
        return None
    if source.gzh_theme_proposal_id:
        return source.gzh_theme_proposal_id
    if source.html_before is None:
        return None

    base_checksum = content_checksum(source.html_before)
    candidates = (
        db.query(GzhThemeProposal)
        .filter(
            GzhThemeProposal.document_id == document_id,
            GzhThemeProposal.session_id == session_id,
            GzhThemeProposal.user_id == user_id,
            GzhThemeProposal.status == GzhThemeProposalStatus.APPROVED,
            GzhThemeProposal.base_checksum == base_checksum,
        )
        .all()
    )
    named_matches = [
        proposal
        for proposal in candidates
        if proposal.theme_name and proposal.theme_name in source.content
    ]
    return named_matches[0].id if len(named_matches) == 1 else None


def mark_proposal_applied(db: Session, proposal_id: str) -> None:
    proposal = db.get(GzhThemeProposal, proposal_id)
    if proposal and proposal.status == GzhThemeProposalStatus.APPROVED:
        proposal.status = GzhThemeProposalStatus.APPLIED
        proposal.applied_at = _utcnow()


def latest_applied_theme_proposal(db: Session, document_id: int) -> GzhThemeProposal | None:
    """Return the newest successful theme snapshot for local visual follow-ups.

    An applied proposal remains immutable and cannot authorize another full
    document replacement. Its saved source is nevertheless the best available
    reference when a later chat request asks to restore a missed component or
    better match the theme's visual details.
    """
    return (
        db.query(GzhThemeProposal)
        .filter(
            GzhThemeProposal.document_id == document_id,
            GzhThemeProposal.status == GzhThemeProposalStatus.APPLIED,
        )
        .order_by(GzhThemeProposal.applied_at.desc(), GzhThemeProposal.created_at.desc())
        .first()
    )


@lru_cache(maxsize=1)
def _upstream_validator():
    path = UPSTREAM_ROOT / "scripts" / "validate_gzh_html.py"
    if not path.exists():
        raise GzhThemeError("未找到上游 HTML 校验脚本")
    spec = importlib.util.spec_from_file_location("vendored_gzh_validator", path)
    if spec is None or spec.loader is None:
        raise GzhThemeError("无法加载上游 HTML 校验脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_gzh_html(html: str) -> dict[str, Any]:
    validator = _upstream_validator()
    errors, warnings, leaf_count = validator.validate(html)
    return {
        "hasError": bool(errors),
        "hasWarning": bool(warnings),
        "errors": list(errors),
        "warnings": list(warnings),
        "leafCount": int(leaf_count),
    }


@lru_cache(maxsize=1)
def _upstream_component_linter():
    path = UPSTREAM_ROOT / "scripts" / "component_lint.py"
    if not path.exists():
        raise GzhThemeError("未找到上游组件库检查脚本")
    spec = importlib.util.spec_from_file_location("vendored_gzh_component_linter", path)
    if spec is None or spec.loader is None:
        raise GzhThemeError("无法加载上游组件库检查脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lint_theme_source(source_markdown: str) -> list[dict[str, str]]:
    """Run the vendor component linter without exposing a mutable vendor tree."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", prefix="gzh-theme-", delete=False
        ) as temporary_file:
            temporary_file.write(source_markdown)
            temporary_path = Path(temporary_file.name)
        # The vendored linter currently uses ``open(...).read()``. It is safe
        # for this short-lived file, but avoid surfacing its ResourceWarning in
        # the application test/output stream.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            _, findings = _upstream_component_linter().lint_file(str(temporary_path))
        result = [{"level": level, "message": message} for level, message in findings]
        seen = {(item["level"], item["message"]) for item in result}

        def add_error(message: str) -> None:
            key = ("ERROR", message)
            if key not in seen:
                seen.add(key)
                result.append({"level": "ERROR", "message": message})

        for html in _HTML_FENCE.findall(source_markdown):
            strict = validate_gzh_html(html)
            for message in strict["errors"]:
                add_error(message)
            if _UNSUPPORTED_COMPONENT_TAG.search(html):
                add_error("出现不适用于公众号静态排版的交互或图形标签")
            if _UNSUPPORTED_COMPONENT_CSS.search(html):
                add_error("出现不支持的字体注入或 CSS expression")
        return result
    except OSError as exc:
        raise GzhThemeError(f"无法检查自定义主题组件库：{exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                # The temporary file contains only the request body and is not
                # part of the vendor tree. A later OS cleanup is harmless.
                pass
