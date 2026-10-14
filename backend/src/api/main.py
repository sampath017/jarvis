"""
FastAPI Application Entry Point — 100% Local Execution.

Configures application lifespan (Local SQLite setup), middlewares, routers, and CORS.
"""

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Response, status
import uvicorn
import asyncio
import logging
import sqlite3
import sys
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend root directory is in sys.path when executed directly
_backend_root = str(Path(__file__).resolve().parent.parent.parent)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)


try:
    from ..backend.context_automation import ContextAutomationService
    from ..backend.logging_config import configure_logging
    from ..services.database import get_db_path, init_database
    from ..settings import LOG_LEVEL, NOTIFICATION_SWEEP_SECONDS, PORT
    from .middleware import RequestLimitingMiddleware, StructuredLoggingMiddleware
    from .routers import automation, commands, context_events, sync, file_memories
except (ImportError, ValueError):
    from src.backend.context_automation import ContextAutomationService
    from src.backend.logging_config import configure_logging
    from src.services.database import get_db_path, init_database
    from src.settings import LOG_LEVEL, NOTIFICATION_SWEEP_SECONDS, PORT
    from src.api.middleware import RequestLimitingMiddleware, StructuredLoggingMiddleware
    from src.api.routers import automation, commands, context_events, sync, file_memories


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from ..services.mobile_scope import mobile_only
    if not mobile_only():
        init_database()

    try:
        from ..settings import (
            MAX_DAILY_TOKENS,
            MAX_TOKENS_PER_CALL,
            OPENROUTER_MODEL_TIER1,
            OPENROUTER_MODEL_TIER2,
            RATE_LIMIT_PER_USER_PER_MINUTE,
        )
    except (ImportError, ValueError):
        from src.settings import (
            MAX_DAILY_TOKENS,
            MAX_TOKENS_PER_CALL,
            OPENROUTER_MODEL_TIER1,
            OPENROUTER_MODEL_TIER2,
            RATE_LIMIT_PER_USER_PER_MINUTE,
        )

    logger.info("=" * 72)
    logger.info(
        "🚀 [APP_STARTUP] Jarvis Context-Aware Agent API Started Successfully")
    logger.info(
        "• Service: jarvis-backend | Port: %d | Cloud Run (asia-south1)", PORT)
    logger.info("• LLM Tier 1: %s", OPENROUTER_MODEL_TIER1)
    logger.info("• LLM Tier 2: %s", OPENROUTER_MODEL_TIER2)
    logger.info("• Storage: local SQLite; Android retains durable personal data")
    from .spend_policy import OPENROUTER_DAILY_BUDGET_USD
    logger.info("• AI allowance: $%.2f/day | %d req/min | no daily token ceiling",
                OPENROUTER_DAILY_BUDGET_USD, RATE_LIMIT_PER_USER_PER_MINUTE)
    from ..settings import LLM_BUDGET_PROFILE, MAX_DAILY_LLM_CALLS
    logger.info("• AI budget profile: %s | daily calls: %d | reset: midnight IST",
                LLM_BUDGET_PROFILE, MAX_DAILY_LLM_CALLS)
    logger.info("=" * 72)

    stop_sweeper = asyncio.Event()
    sweeper = None if mobile_only() else asyncio.create_task(
        _notification_sweeper(stop_sweeper))
    try:
        yield
    finally:
        stop_sweeper.set()
        if sweeper:
            _ = sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper
        logger.info("Shutting down local Jarvis API")


async def _notification_sweeper(stop: asyncio.Event) -> None:
    """Persist due time reminders even if no mobile client is polling."""
    while not stop.is_set():
        try:
            from ..services.runtime_power import RuntimePower
            power = RuntimePower()
            # Off instances sleep locally; only an incoming control/request reads
            # the persisted state again. No RecordStore polling while powered off.
            if not power.locally_enabled or not await asyncio.to_thread(power.enabled, fresh=True):
                await asyncio.sleep(NOTIFICATION_SWEEP_SECONDS)
                continue
            _ = await asyncio.to_thread(ContextAutomationService().process_due_reminders)
            from ..services.push_notifications import PushNotifications
            from ..services.background_tasks import BackgroundTasks
            from ..services.record_store import RecordStore

            def refresh_delivery():
                if not power.enabled():
                    return
                fs = RecordStore()
                if not fs.is_available:
                    return
                users = {'jarvis_local_user'}
                for reminder in fs.get_reminders():
                    uid = reminder.get('uid') or 'jarvis_local_user'
                    users.add(uid)
                    BackgroundTasks().schedule_reminder(uid, reminder)
                    if reminder.get('activity_delay_seconds'):
                        from ..services.activity_reminder_timers import ActivityReminderTimers
                        ActivityReminderTimers(fs).reconcile(uid, reminder)
                for uid in users:
                    PushNotifications().deliver(uid)
            await asyncio.to_thread(refresh_delivery)
        except Exception:
            logger.exception("Notification sweeper failed")
        try:
            _ = await asyncio.wait_for(stop.wait(), timeout=NOTIFICATION_SWEEP_SECONDS)
        except TimeoutError:
            continue


async def health_check(response: Response) -> dict[str, object]:
    """
    Liveness and readiness probe for the Jarvis local API.

    Verifies service operational status, environment mode, and local SQLite
    database connectivity. Returns HTTP 200 when healthy, or HTTP 503 if any
    critical dependency fails.
    """
    try:
        from ..backend.logging_config import IST_TZ
    except (ImportError, ValueError):
        from src.backend.logging_config import IST_TZ

    health_status: dict[str, object] = {
        "status": "healthy",
        "service": "jarvis-local-api",
        "mode": "local",
        "timestamp": datetime.now(IST_TZ).isoformat(),
        "timezone": "IST (Asia/Kolkata)",
        "database": {"status": "healthy"},
        "storage": {
            "backend": "mobile-only",
            "mobile_is_authoritative": True,
            "server_storage": "request-memory",
            "document_index": "existing-chroma",
        },
    }
    from ..settings import LLM_BUDGET_PROFILE, MAX_DAILY_LLM_CALLS, MAX_DAILY_TOKENS, RATE_LIMIT_PER_USER_PER_MINUTE
    from .spend_policy import OPENROUTER_DAILY_BUDGET_USD
    health_status['ai_budget'] = {'profile': LLM_BUDGET_PROFILE,
                                  'daily_tokens': MAX_DAILY_TOKENS or None, 'daily_calls': MAX_DAILY_LLM_CALLS or None,
                                  'daily_budget_usd': OPENROUTER_DAILY_BUDGET_USD,
                                  'requests_per_minute': RATE_LIMIT_PER_USER_PER_MINUTE,
                                  'reset_timezone': 'Asia/Kolkata'}

    try:
        from ..services.mobile_scope import mobile_only
        if not mobile_only():
            db_path = get_db_path()
            with sqlite3.connect(db_path, timeout=2.0) as conn:
                conn.execute("SELECT 1;").fetchone()

    except Exception as exc:
        logger.warning("Database health check probe failed: %s", exc)
        health_status["status"] = "unhealthy"
        health_status["database"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_status


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Jarvis Local API",
        description="Jarvis Context-Aware Mobile Agent Local Backend",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 1. Mount standard middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLimitingMiddleware)
    app.add_middleware(StructuredLoggingMiddleware)
    from .power_middleware import PowerMiddleware
    app.add_middleware(PowerMiddleware)

    # 2. Register routers
    from ..services.mobile_scope import mobile_only
    if mobile_only():
        from .routers import mobile_compute
        from fastapi import APIRouter
        compute_routes = APIRouter()
        for route in commands.router.routes:
            if route.path.startswith('/commands/'):
                compute_routes.routes.append(route)
        for route in context_events.router.routes:
            if getattr(route, 'path', None) == '/context-events':
                compute_routes.routes.append(route)
        for route in file_memories.router.routes:
            if route.path.endswith('/analyze'):
                compute_routes.routes.append(route)
        from .routers import drive_index
        for route in drive_index.router.routes:
            if route.path in {'/drive-index/status', '/drive-index/search', '/drive-index/search-contents', '/drive-index/evidence', '/drive-index/files/{file_id}'}:
                compute_routes.routes.append(route)
        app.include_router(compute_routes)
        app.include_router(mobile_compute.router)
        from .mobile_middleware import MobileStateMiddleware
        app.add_middleware(MobileStateMiddleware)
    else:
        app.include_router(context_events.router)
        app.include_router(commands.router)
        app.include_router(automation.router)
        app.include_router(file_memories.router)
        from .routers import drive_index
        app.include_router(drive_index.router)
        app.include_router(sync.router)
        from .routers import incremental_sync
        app.include_router(incremental_sync.router)
        from .routers import chat_archives
        app.include_router(chat_archives.router)
        app.include_router(chat_archives.background_router)
        from .routers import server_google
        app.include_router(server_google.router)
        from .routers import runtime_power
        app.include_router(runtime_power.router)

    # 3. Liveness/Readiness probes and Root landing
    app.add_api_route(
        "/", health_check, methods=["GET"], status_code=status.HTTP_200_OK, tags=["monitoring"])
    app.add_api_route("/health", health_check,
                      methods=["GET"], status_code=status.HTTP_200_OK, tags=["monitoring"])

    return app


app = create_app()


def run() -> None:
    """CLI script entry point (runs uvicorn)."""
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=True,
        reload_dirs=["src"],
        reload_excludes=["*.db", "*.db-*", "data/*", "logs/*", "*.log"],
    )


if __name__ == "__main__":
    run()
