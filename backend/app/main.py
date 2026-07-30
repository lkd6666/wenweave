import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.models  # noqa: F401  确保所有模型被注册到 Base.metadata，创建表时不会遗漏
from app.api.router import api_router
from app.bootstrap import (
    SCHEMA_REVISION,
    backfill_official_deepseek_thinking_models,
    migrate_schema,
    recover_interrupted_agent_runs,
    schema_migration_lock,
    seed_default_admin,
)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.agent_run_manager import cleanup_expired_agent_run_events
from app.services.tool_output_store import cleanup_expired_tool_outputs
from app.services.chat_images import cleanup_expired_drafts
from app.services.gzh_theme_generation import cleanup_expired_reference_assets
from app.services.layout_reference import cleanup_expired_layout_references, layout_reference_cache
from app.services.web_article_import import cleanup_expired_web_article_imports
from app.services.operation_logs import (
    capture_request_context,
    persist_request_audit,
    request_metadata,
    reset_operation_request_metadata,
    reset_operation_request_id,
    set_operation_request_metadata,
    set_operation_request_id,
    with_request_id,
)


logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _run_cleanup_cycle(app: FastAPI) -> None:
    """Run independent cleanup jobs without letting one poison later cycles."""
    failures: list[str] = []
    cleaners = (
        ("tool_outputs", cleanup_expired_tool_outputs),
        ("chat_image_drafts", cleanup_expired_drafts),
        ("theme_reference_assets", cleanup_expired_reference_assets),
        ("agent_run_events", cleanup_expired_agent_run_events),
        ("layout_references", cleanup_expired_layout_references),
        ("web_article_imports", cleanup_expired_web_article_imports),
    )
    for name, cleaner in cleaners:
        db = SessionLocal()
        try:
            cleaner(db)
        except Exception:  # noqa: BLE001 - the next scheduled cycle must still execute.
            db.rollback()
            failures.append(name)
            logger.exception("cleanup_failed cleaner=%s", name)
        finally:
            db.close()
    try:
        layout_reference_cache.purge()
    except Exception:  # noqa: BLE001
        failures.append("layout_reference_cache")
        logger.exception("cleanup_failed cleaner=layout_reference_cache")

    completed_at = _utcnow()
    app.state.cleanup_last_attempt_at = completed_at
    if failures:
        app.state.cleanup_last_error = ",".join(failures)
    else:
        app.state.cleanup_last_error = ""
        app.state.cleanup_last_success_at = completed_at


def _check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": SCHEMA_REVISION},
        ).scalar()
        if revision != SCHEMA_REVISION:
            raise RuntimeError("schema revision is not ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cleanup_last_attempt_at = None
    app.state.cleanup_last_success_at = None
    app.state.cleanup_last_error = ""
    # Schema mutations and startup recovery must be performed by one worker.
    # Other workers wait on the advisory/file lock before accepting requests.
    with schema_migration_lock():
        Base.metadata.create_all(bind=engine)
        migrate_schema()
        db = SessionLocal()
        try:
            recover_interrupted_agent_runs(db)
            backfill_official_deepseek_thinking_models(db)
            seed_default_admin(db)
        finally:
            db.close()
    # Waiting questions are durable but their lightweight local timers are
    # process-local. Recreate them after startup without consuming an Agent
    # execution slot.
    from app.api.routes.chat import restore_waiting_user_question_timeouts

    await restore_waiting_user_question_timeouts()
    interval = max(60, int(settings.CHAT_TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS))

    async def cleanup_loop() -> None:
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(_run_cleanup_cycle, app)

    await asyncio.to_thread(_run_cleanup_cycle, app)
    cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


settings = get_settings()
settings.validate_runtime_security()
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

MULTIPART_OVERHEAD_ALLOWANCE = 256 * 1024
MAX_IMPORT_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BRANDING_ASSET_BYTES = 2 * 1024 * 1024


def _upload_size_limit(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == 6 and parts[:3] == ["api", "documents", "imports"] and parts[4:] == ["source", "upload"]:
        return MAX_IMPORT_UPLOAD_BYTES
    if len(parts) == 7 and parts[:3] == ["api", "documents", "imports"] and parts[4] == "assets" and parts[6] == "upload":
        return MAX_IMAGE_UPLOAD_BYTES
    if len(parts) == 4 and parts[:2] == ["api", "documents"] and parts[2].isdigit() and parts[3] == "images":
        return MAX_IMAGE_UPLOAD_BYTES
    if len(parts) == 4 and parts[:2] == ["api", "documents"] and parts[2].isdigit() and parts[3] == "chat-images":
        return MAX_IMAGE_UPLOAD_BYTES
    if parts == ["api", "gzh-theme-assets"]:
        return MAX_IMAGE_UPLOAD_BYTES
    if parts in (["api", "branding", "logo"], ["api", "branding", "favicon"]):
        return MAX_BRANDING_ASSET_BYTES
    return None


def _json_size_limit(path: str) -> int:
    if path.endswith("/content") or path.startswith("/api/documents/imports/") or path.count("/") == 3:
        return settings.MAX_DOCUMENT_HTML_BYTES + MULTIPART_OVERHEAD_ALLOWANCE
    return settings.MAX_JSON_BODY_BYTES


@app.middleware("http")
async def reject_oversized_document_uploads(request: Request, call_next):
    """Reject unbounded multipart and JSON bodies before parsing them in memory."""
    path = request.url.path
    limit = _upload_size_limit(path) if request.method == "POST" else None
    content_type = request.headers.get("content-type", "").lower()
    if limit is None and request.method in {"POST", "PUT", "PATCH"} and (
        "application/json" in content_type or content_type.endswith("+json")
    ):
        limit = _json_size_limit(path)
    if limit is not None:
        raw_length = request.headers.get("content-length")
        if raw_length is None:
            return JSONResponse(status_code=411, content={"detail": "请求必须包含 Content-Length"})
        try:
            content_length = int(raw_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "上传请求的 Content-Length 无效"})
        if content_length < 0 or content_length > limit:
            return JSONResponse(status_code=413, content={"detail": "请求内容超过允许的大小"})
    return await call_next(request)


@app.middleware("http")
async def request_correlation(request: Request, call_next):
    candidate = request.headers.get("x-request-id", "").strip()
    existing = str(getattr(request.state, "request_id", "")).strip()
    request_id = existing if 0 < len(existing) <= 128 and existing.isprintable() else (
        candidate if 0 < len(candidate) <= 128 and candidate.isprintable() else str(uuid4())
    )
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed request_id=%s method=%s path=%s", request_id, request.method, request.url.path)
        raise
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def operation_audit(request: Request, call_next):
    """Persist concise business-operation records without retaining request bodies."""
    candidate = request.headers.get("x-request-id", "").strip()
    request_id = candidate if 0 < len(candidate) <= 128 and candidate.isprintable() else str(uuid4())
    request.state.request_id = request_id
    request_token = set_operation_request_id(request_id)
    metadata_token = set_operation_request_metadata(request_metadata(request))
    try:
        context = await capture_request_context(request)
        if context is None:
            return await call_next(request)
        try:
            response = await call_next(request)
        except Exception:
            persist_request_audit(context, 500, exception=True)
            raise
        context = with_request_id(context, str(getattr(request.state, "request_id", "")))
        if not context.route.deferred_terminal or response.status_code >= 400:
            persist_request_audit(context, response.status_code)
        return response
    finally:
        reset_operation_request_metadata(metadata_token)
        reset_operation_request_id(request_token)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health/live")
def health_live():
    return {"status": "ok", "app": settings.APP_NAME}


async def _readiness_response() -> JSONResponse:
    database_ok = True
    database_error = ""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_check_database),
            timeout=max(0.2, float(settings.HEALTH_READINESS_TIMEOUT_SECONDS)),
        )
    except Exception as exc:  # noqa: BLE001
        database_ok = False
        database_error = type(exc).__name__
    last_success = getattr(app.state, "cleanup_last_success_at", None)
    interval = max(60, int(settings.CHAT_TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS))
    cleanup_stale = last_success is None or (_utcnow() - last_success).total_seconds() > max(300, interval * 3)
    ready = database_ok and not cleanup_stale
    payload = {
        "status": "ok" if ready else "degraded",
        "app": settings.APP_NAME,
        "database": "ok" if database_ok else "unavailable",
        "cleanup": {
            "last_success_at": last_success.isoformat() if last_success else None,
            "last_error": getattr(app.state, "cleanup_last_error", ""),
            "stale": cleanup_stale,
        },
    }
    if database_error:
        payload["database_error"] = database_error
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@app.get("/api/health/ready")
async def health_ready():
    return await _readiness_response()


@app.get("/api/health")
async def health():
    """Compatibility endpoint: readiness is the meaningful operational health."""
    return await _readiness_response()


# 生产环境下，前端 `npm run build` 产物会输出到 frontend/dist，由后端一并托管，
# 实现"单体部署"。本地开发时该目录不存在，前端走 Vite dev server 单独运行即可。
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


class SpaStaticFiles(StaticFiles):
    """Serve the frontend entry point for client-side routes, but not API misses."""

    async def get_response(self, path: str, scope):
        normalized_path = path.lstrip("/")
        request_path = str(scope.get("path", "")).lstrip("/")
        is_api_path = (
            normalized_path == "api"
            or normalized_path.startswith("api/")
            or request_path == "api"
            or request_path.startswith("api/")
        )
        can_fall_back = not is_api_path and not Path(normalized_path).suffix
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not can_fall_back:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and can_fall_back:
            return await super().get_response("index.html", scope)
        return response


if FRONTEND_DIST.exists():
    app.mount("/", SpaStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
