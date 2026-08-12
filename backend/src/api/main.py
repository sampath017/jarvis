"""
FastAPI Application Entry Point — 100% Local Execution.

Configures application lifespan (Local SQLite setup), middlewares, routers, and CORS.
"""

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

import uvicorn
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

try:
    from ..backend.context_automation import ContextAutomationService
    from ..backend.logging_config import configure_logging
    from ..services.database import get_db_path, init_database
    from ..settings import LOG_LEVEL, NOTIFICATION_SWEEP_SECONDS, PORT
    from .middleware import RequestLimitingMiddleware, StructuredLoggingMiddleware
    from .routers import automation, commands, context_events
except (ImportError, ValueError):
    from src.backend.context_automation import ContextAutomationService
    from src.backend.logging_config import configure_logging
    from src.services.database import get_db_path, init_database
    from src.settings import LOG_LEVEL, NOTIFICATION_SWEEP_SECONDS, PORT
    from src.api.middleware import RequestLimitingMiddleware, StructuredLoggingMiddleware
    from src.api.routers import automation, commands, context_events


configure_logging()
logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting up: initializing local SQLite database")
    init_database()
    stop_sweeper = asyncio.Event()
    sweeper = asyncio.create_task(_notification_sweeper(stop_sweeper))
    try:
        yield
    finally:
        stop_sweeper.set()
        _ = sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper
        logger.info("Shutting down local Jarvis API")


async def _notification_sweeper(stop: asyncio.Event) -> None:
    """Persist due time reminders even if no mobile client is polling."""
    while not stop.is_set():
        try:
            _ = ContextAutomationService().process_due_reminders()
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
    health_status: dict[str, object] = {
        "status": "healthy",
        "service": "jarvis-local-api",
        "mode": "local",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": {"status": "healthy"},
    }

    try:
        db_path = get_db_path()
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            cursor = conn.cursor()
            _ = cursor.execute("SELECT 1;")
            cursor.fetchone()
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

    # 2. Register routers
    app.include_router(context_events.router)
    app.include_router(commands.router)
    app.include_router(automation.router)

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
