"""汇总所有子路由。后续每新增一个模块（用户管理/AI模型/存储/文档/对话/合规检测），
在此处 include 即可，main.py 不需要再改动。"""
from fastapi import APIRouter

from app.api.routes import ai_providers, auth, chat, compliance, document_groups, documents, layout_references, models, storage, user_groups, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(user_groups.router)
api_router.include_router(models.router)
api_router.include_router(ai_providers.router)
api_router.include_router(storage.router)
api_router.include_router(document_groups.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(compliance.router)
api_router.include_router(layout_references.router)
