import asyncio
import atexit
import faulthandler
import logging
import os
import signal
import sys
import threading
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
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
    migrate_anthropic_thinking_models,
    migrate_gemini_native_providers,
    prepare_mysql_image_model_access_tables,
    recover_expired_agent_runs,
    recover_interrupted_agent_runs,
    schema_migration_lock,
    seed_default_admin,
)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.agent_run_manager import WORKER_ID, cleanup_expired_agent_run_events
from app.services.tool_output_store import cleanup_expired_tool_outputs
from app.services.token_budget import preload_tokenizer
from app.services.chat_images import cleanup_expired_drafts
from app.services.gzh_theme_generation import cleanup_expired_reference_assets
from app.services.layout_reference import (
    MAX_REFERENCE_IMAGE_TOTAL_BYTES,
    MAX_RESPONSE_BYTES,
    cleanup_expired_layout_capture_sessions,
    cleanup_expired_layout_references,
    layout_reference_cache,
)
from app.services.web_article_import import cleanup_expired_web_article_imports
from app.services.image_generation import cleanup_unused_assets, recover_pending_generations, start_generation
from app.services.operation_logs import (
    capture_request_context,
    persist_request_audit,
    request_metadata,
    reset_operation_request_metadata,
    reset_operation_request_id,
    set_operation_request_metadata,
    set_operation_request_id,
    with_request_audit_actor,
    with_request_id,
)
from app.services.runtime_diagnostics import log_process_memory, read_process_memory
from app.services.wechat_compliance import close_official_compliance_engine


logger = logging.getLogger(__name__)
LOG_TIMESTAMP_FORMAT = "%(asctime)s %(levelname)s [pid=%(process)d] %(name)s: %(message)s"
LOG_TIMESTAMP_DATE_FORMAT = "%Y-%m-%d %H:%M:%S%z"


def _timestamped_log_formatter() -> logging.Formatter:
    """Keep all ordinary worker logs on one locally sortable timeline."""
    return logging.Formatter(LOG_TIMESTAMP_FORMAT, datefmt=LOG_TIMESTAMP_DATE_FORMAT)


def _configure_timestamped_logging() -> None:
    """Apply timestamps to app, Uvicorn and Supervisor-inherited handlers."""
    handlers: list[logging.Handler] = []
    seen_handler_ids: set[int] = set()
    for logger_name in (None, "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(logger_name)
        for handler in target.handlers:
            if id(handler) not in seen_handler_ids:
                handlers.append(handler)
                seen_handler_ids.add(id(handler))
    for handler in handlers:
        handler.setFormatter(_timestamped_log_formatter())


class _SuccessfulReadAccessLogFilter(logging.Filter):
    """Keep the worker log focused on writes and failed read requests."""

    _READ_METHODS = {"GET", "HEAD", "OPTIONS"}

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's access logger uses
        # (client_addr, method, path, http_version, status_code) as args.
        # Keep this defensive so an upstream Uvicorn format change cannot hide
        # a request unexpectedly.
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method = str(args[1]).upper()
        try:
            status_code = int(args[4])
        except (TypeError, ValueError):
            return True
        return not (method in self._READ_METHODS and 200 <= status_code < 400)


def _configure_worker_logging() -> None:
    """Avoid normal frontend polling/static reads drowning out failure evidence."""
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _SuccessfulReadAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(_SuccessfulReadAccessLogFilter())


def _report_unhandled_process_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return
    logger.critical(
        "unhandled_process_exception pid=%s worker_id=%s",
        os.getpid(),
        WORKER_ID,
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def _report_unhandled_thread_exception(args: threading.ExceptHookArgs) -> None:
    if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
        return
    logger.critical(
        "unhandled_thread_exception pid=%s worker_id=%s thread=%s",
        os.getpid(),
        WORKER_ID,
        args.thread.name if args.thread else "unknown",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _install_asyncio_exception_reporting() -> None:
    """Report detached task failures with their complete traceback."""
    loop = asyncio.get_running_loop()

    def report(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, BaseException):
            logger.error(
                "unhandled_asyncio_exception pid=%s worker_id=%s message=%s",
                os.getpid(),
                WORKER_ID,
                context.get("message", ""),
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return
        logger.error(
            "unhandled_asyncio_error pid=%s worker_id=%s context=%r",
            os.getpid(),
            WORKER_ID,
            context,
        )

    loop.set_exception_handler(report)


def _configure_worker_diagnostics() -> None:
    """Enable process-local crash evidence for each Uvicorn worker."""
    try:
        faulthandler.enable(all_threads=True)
        sigusr2 = getattr(signal, "SIGUSR2", None)
        if sigusr2 is not None:
            faulthandler.register(sigusr2, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        # Diagnostics must never prevent the application from starting on a
        # restricted runtime or local Windows development environment.
        logger.exception("agent_worker_diagnostics_setup_failed pid=%s", os.getpid())


def _log_worker_exit() -> None:
    # SIGKILL and a hard process crash cannot reach this handler. It provides
    # a positive signal for orderly worker shutdowns in the supervisor log.
    logger.warning("agent_worker_exit pid=%s worker_id=%s", os.getpid(), WORKER_ID)


_configure_worker_diagnostics()
_configure_timestamped_logging()
_configure_worker_logging()
sys.excepthook = _report_unhandled_process_exception
threading.excepthook = _report_unhandled_thread_exception
atexit.register(_log_worker_exit)


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
        ("layout_capture_sessions", cleanup_expired_layout_capture_sessions),
        ("web_article_imports", cleanup_expired_web_article_imports),
        ("generated_image_assets", cleanup_unused_assets),
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


def _recover_expired_agent_runs() -> int:
    """Finish lost workers promptly instead of waiting for an SSE reconnect."""
    db = SessionLocal()
    try:
        recovered = recover_expired_agent_runs(db)
        if recovered:
            logger.warning("agent_run_lease_recovered count=%s", recovered)
        return recovered
    except Exception:  # noqa: BLE001 - a later interval retries transient database failures.
        db.rollback()
        logger.exception("agent_run_lease_recovery_failed")
        return 0
    finally:
        db.close()


def _check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": SCHEMA_REVISION},
        ).scalar()
        if revision != SCHEMA_REVISION:
            raise RuntimeError("schema revision is not ready")


def _schema_tables_before_image_model_access():
    access_table_names = {"image_model_user_access", "image_model_group_access"}
    return [table for table in Base.metadata.sorted_tables if table.name not in access_table_names]


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_started = stage_started = perf_counter()

    def record_startup_stage(stage: str) -> None:
        nonlocal stage_started
        now = perf_counter()
        logger.warning("startup_stage_complete stage=%s elapsed_seconds=%.3f", stage, now - stage_started)
        stage_started = now

    _install_asyncio_exception_reporting()
    await asyncio.to_thread(preload_tokenizer)
    record_startup_stage("tokenizer")
    memory = read_process_memory()
    logger.warning(
        "agent_worker_started pid=%s worker_id=%s rss_kib=%s swap_kib=%s",
        os.getpid(),
        WORKER_ID,
        memory.rss_kib,
        memory.swap_kib,
    )
    log_process_memory(
        logger,
        stage="worker_startup",
        worker_id=WORKER_ID,
        level=logging.WARNING,
    )
    app.state.cleanup_last_attempt_at = None
    app.state.cleanup_last_success_at = None
    app.state.cleanup_last_error = ""
    pending_image_generation_ids: list[str] = []
    # Schema mutations and startup recovery must be performed by one worker.
    # Other workers wait on the advisory/file lock before accepting requests.
    with schema_migration_lock():
        record_startup_stage("migration_lock")
        if engine.url.drivername.startswith("mysql"):
            # Legacy image-model IDs can differ from the current BIGINT UNSIGNED
            # contract. Create every parent first, then create the two access
            # tables with the actual parent ID types before static DDL sees them.
            Base.metadata.create_all(bind=engine, tables=_schema_tables_before_image_model_access())
            prepare_mysql_image_model_access_tables()
        Base.metadata.create_all(bind=engine)
        record_startup_stage("create_tables")
        migrate_schema()
        record_startup_stage("migrate_schema")
        db = SessionLocal()
        try:
            recover_interrupted_agent_runs(db)
            pending_image_generation_ids = recover_pending_generations()
            record_startup_stage("recover_jobs")
            backfill_official_deepseek_thinking_models(db)
            migrate_anthropic_thinking_models(db)
            migrate_gemini_native_providers(db)
            record_startup_stage("migrate_models")
            from app.services.image_library import backfill_generated_assets, backfill_imported_assets

            backfill_generated_assets(db)
            record_startup_stage("backfill_generated_assets")
            imported_assets = backfill_imported_assets(db)
            record_startup_stage("backfill_imported_assets")
            if imported_assets:
                logger.warning("startup_imported_assets_migrated count=%s", imported_assets)
            seed_default_admin(db)
        finally:
            db.close()
    # Waiting questions are durable but their lightweight local timers are
    # process-local. Recreate them after startup without consuming an Agent
    # execution slot.
    from app.api.routes.chat import restore_waiting_user_question_timeouts

    await restore_waiting_user_question_timeouts()
    for generation_id in pending_image_generation_ids:
        start_generation(generation_id)
    interval = max(60, int(settings.CHAT_TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS))

    async def cleanup_loop() -> None:
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(_run_cleanup_cycle, app)

    recovery_interval = max(1, int(settings.CHAT_AGENT_LEASE_RECOVERY_INTERVAL_SECONDS))

    async def lease_recovery_loop() -> None:
        while True:
            await asyncio.sleep(recovery_interval)
            await asyncio.to_thread(_recover_expired_agent_runs)

    await asyncio.to_thread(_run_cleanup_cycle, app)
    record_startup_stage("restore_timers_and_cleanup")
    logger.warning("startup_complete elapsed_seconds=%.3f", perf_counter() - startup_started)
    cleanup_task = asyncio.create_task(cleanup_loop())
    recovery_task = asyncio.create_task(lease_recovery_loop())
    try:
        yield
    finally:
        for task in (cleanup_task, recovery_task):
            task.cancel()
        for task in (cleanup_task, recovery_task):
            with suppress(asyncio.CancelledError):
                await task
        # The checker is lazy, so this is a no-op when no model requested a
        # verification. Closing it here releases its Chromium process before
        # Uvicorn tears down the worker.
        await asyncio.to_thread(close_official_compliance_engine)


settings = get_settings()
settings.validate_runtime_security()
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

MULTIPART_OVERHEAD_ALLOWANCE = 256 * 1024
# Permit a 50 MiB file plus the enclosing multipart form data.
MAX_IMPORT_UPLOAD_BYTES = 50 * 1024 * 1024 + MULTIPART_OVERHEAD_ALLOWANCE
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BRANDING_ASSET_BYTES = 2 * 1024 * 1024
MAX_LAYOUT_CAPTURE_UPLOAD_BYTES = MAX_RESPONSE_BYTES + MAX_REFERENCE_IMAGE_TOTAL_BYTES + MULTIPART_OVERHEAD_ALLOWANCE


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
    if (
        len(parts) == 5
        and parts[:3] == ["api", "layout-references", "capture-sessions"]
        and parts[4] == "complete"
    ):
        return MAX_LAYOUT_CAPTURE_UPLOAD_BYTES
    if (
        len(parts) == 6
        and parts[:4] == ["api", "documents", "link-imports", "capture-sessions"]
        and parts[5] == "complete"
    ):
        return MAX_LAYOUT_CAPTURE_UPLOAD_BYTES
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
            context = with_request_audit_actor(context, request)
            context = with_request_id(context, str(getattr(request.state, "request_id", "")))
            persist_request_audit(context, 500, exception=True)
            raise
        context = with_request_audit_actor(context, request)
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
