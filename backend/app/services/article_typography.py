from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.article_typography_settings import ArticleTypographySettings


TYPOGRAPHY_SETTINGS_ID = 1
DEFAULT_ARTICLE_TYPOGRAPHY_SETTINGS: dict[str, float | str] = {
    "horizontal_padding_px": 4,
    "paragraph_spacing_px": 20,
    "font_size_px": 15,
    "line_height_em": 2,
    "letter_spacing_px": 1,
    "text_indent_em": 2,
    "text_color": "#000000",
}


def get_or_create_typography_settings(db: Session) -> ArticleTypographySettings:
    settings = db.get(ArticleTypographySettings, TYPOGRAPHY_SETTINGS_ID)
    if settings is None:
        settings = ArticleTypographySettings(
            id=TYPOGRAPHY_SETTINGS_ID,
            **DEFAULT_ARTICLE_TYPOGRAPHY_SETTINGS,
        )
        db.add(settings)
        db.flush()
    return settings


def typography_settings_payload(settings: ArticleTypographySettings | None = None) -> dict[str, Any]:
    values = DEFAULT_ARTICLE_TYPOGRAPHY_SETTINGS if settings is None else {
        "horizontal_padding_px": settings.horizontal_padding_px,
        "paragraph_spacing_px": settings.paragraph_spacing_px,
        "font_size_px": settings.font_size_px,
        "line_height_em": settings.line_height_em,
        "letter_spacing_px": settings.letter_spacing_px,
        "text_indent_em": settings.text_indent_em,
        "text_color": settings.text_color,
    }
    return {
        "horizontal_padding_px": float(values["horizontal_padding_px"]),
        "paragraph_spacing_px": float(values["paragraph_spacing_px"]),
        "font_size_px": float(values["font_size_px"]),
        "line_height_em": float(values["line_height_em"]),
        "letter_spacing_px": float(values["letter_spacing_px"]),
        "text_indent_em": float(values["text_indent_em"]),
        "text_color": str(values["text_color"]).upper(),
        # This payload also becomes part of an Agent run's durable JSON
        # context, so ORM datetimes must not escape as Python objects.
        "updated_at": (
            settings.updated_at.isoformat()
            if settings is not None and settings.updated_at
            else None
        ),
    }
