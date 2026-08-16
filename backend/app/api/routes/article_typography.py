from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.article_typography import ArticleTypographySettingsRead, ArticleTypographySettingsUpdate
from app.services.article_typography import get_or_create_typography_settings, typography_settings_payload


router = APIRouter(prefix="/api/article-typography-settings", tags=["article-typography-settings"])


@router.get("", response_model=ArticleTypographySettingsRead)
def get_article_typography_settings(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    del current_user
    settings = get_or_create_typography_settings(db)
    db.commit()
    db.refresh(settings)
    return typography_settings_payload(settings)


@router.put("", response_model=ArticleTypographySettingsRead)
def update_article_typography_settings(
    payload: ArticleTypographySettingsUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_or_create_typography_settings(db)
    for field, value in payload.model_dump().items():
        setattr(settings, field, value)
    settings.updated_by_id = current_user.id
    db.commit()
    db.refresh(settings)
    return typography_settings_payload(settings)
