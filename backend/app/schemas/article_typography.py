from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ArticleTypographySettingsRead(BaseModel):
    horizontal_padding_px: float
    paragraph_spacing_px: float
    font_size_px: float
    line_height_em: float
    letter_spacing_px: float
    text_indent_em: float
    text_color: str
    updated_at: datetime | None = None


class ArticleTypographySettingsUpdate(BaseModel):
    horizontal_padding_px: float = Field(ge=0, le=24)
    paragraph_spacing_px: float = Field(ge=0, le=48)
    font_size_px: float = Field(ge=12, le=20)
    line_height_em: float = Field(ge=1.2, le=3.0)
    letter_spacing_px: float = Field(ge=0, le=4)
    text_indent_em: float = Field(ge=0, le=4)
    text_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator(
        "horizontal_padding_px",
        "paragraph_spacing_px",
        "font_size_px",
        "line_height_em",
        "letter_spacing_px",
        "text_indent_em",
    )
    @classmethod
    def require_tenth_step(cls, value: float) -> float:
        rounded = round(float(value), 1)
        if abs(float(value) - rounded) > 1e-8:
            raise ValueError("数值最多保留一位小数")
        return rounded

    @field_validator("text_color")
    @classmethod
    def normalize_color(cls, value: str) -> str:
        return value.upper()
