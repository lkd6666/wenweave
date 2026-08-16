"""汇总所有子路由。后续每新增一个模块（用户管理/AI模型/存储/文档/对话/合规检测），
在此处 include 即可，main.py 不需要再改动。"""
from fastapi import APIRouter

from app.api.routes import ai_providers, article_typography, auth, branding, chat, compliance, document_groups, document_shares, documents, gzh_themes, image_generations, image_library, image_searches, layout_references, models, operation_logs, storage, template_library, user_groups, users, wechat_accounts, workbench, workboard

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(branding.router)
api_router.include_router(article_typography.router)
api_router.include_router(users.router)
api_router.include_router(user_groups.router)
api_router.include_router(models.router)
api_router.include_router(ai_providers.router)
api_router.include_router(storage.router)
api_router.include_router(storage.public_router)
api_router.include_router(document_groups.router)
api_router.include_router(documents.router)
api_router.include_router(image_generations.router)
api_router.include_router(image_library.router)
api_router.include_router(image_searches.router)
api_router.include_router(workbench.router)
api_router.include_router(document_shares.router)
api_router.include_router(document_shares.public_router)
api_router.include_router(chat.router)
api_router.include_router(chat.user_question_router)
api_router.include_router(compliance.router)
api_router.include_router(layout_references.router)
api_router.include_router(gzh_themes.router)
api_router.include_router(template_library.router)
api_router.include_router(wechat_accounts.router)
api_router.include_router(workboard.router)
api_router.include_router(operation_logs.router)
