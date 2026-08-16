"""供排版工作台使用的模型列表接口（所有已登录用户可访问，不暴露 Provider 密钥）。"""

from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session, selectinload



from app.api.deps import get_current_user

from app.db.session import get_db

from app.models.ai_model import AIModel
from app.models.ai_image_model import AIImageModel
from app.models.user import User
from app.schemas.ai_provider import ImageModelRead, ModelRead
from app.services.model_access import (
    accessible_image_models_query,
    accessible_models_query,
    is_image_model_available,
    is_model_available,
)


router = APIRouter(prefix="/api/models", tags=["models"])





@router.get("", response_model=list[ModelRead])

def list_models(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AIModel]:
    models = (
        accessible_models_query(db.query(AIModel), current_user)
        .options(selectinload(AIModel.provider))
        .order_by(AIModel.is_default.desc(), AIModel.id)
        .all()
    )
    return [model for model in models if is_model_available(model)]


@router.get("/image", response_model=list[ImageModelRead])
def list_image_models(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AIImageModel]:
    models = (
        accessible_image_models_query(db.query(AIImageModel), current_user)
        .options(selectinload(AIImageModel.provider))
        .order_by(AIImageModel.is_default.desc(), AIImageModel.id)
        .all()
    )
    return [model for model in models if is_image_model_available(model)]
