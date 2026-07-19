"""
FastAPI Application Entry Point.

Configures application lifespan (Firebase setup), middlewares, routers, and CORS.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from ..services.firestore_client import init_firebase
from .settings import settings
from .middleware import RequestLimitingMiddleware, StructuredLoggingMiddleware
from .routers import commands, context_events

# ── Cloud Logging Configuration (sys.stdout) ──────────────────────────────────


def configure_logging() -> None:
    """Configures root logging to stdout for native GCP Cloud Logging ingestion."""
    log_level = logging.getLevelName(settings.log_level.upper())
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # Direct stdout handler ingested automatically by Google Cloud Logging
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(log_level)
    root_logger.addHandler(stdout_handler)


configure_logging()
logger = logging.getLogger(__name__)


# ── Lifespan handler (initialises Firebase once) ─────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise Firebase Admin SDK with project settings
    logger.info("Starting up: initialising Firebase")
    init_firebase(project_id=settings.firebase_project_id or None)
    yield
    logger.info("Shutting down")


# ── App construction ─────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Jarvis API",
        description="Jarvis Context-Aware Mobile Agent Backend",
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

    # 3. Liveness/Readiness probes and Root landing
    @app.get("/", status_code=status.HTTP_200_OK, tags=["monitoring"])
    @app.get("/health", status_code=status.HTTP_200_OK, tags=["monitoring"])
    def health_check() -> dict[str, str]:
        """Simple liveness/readiness probe."""
        return {"status": "healthy", "service": "jarvis-api"}

    return app


app = create_app()


def run() -> None:
    """CLI script entry point (runs uvicorn)."""
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
