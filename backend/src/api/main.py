"""Phone-owned SQLite processing API with disposable request workspaces."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from ..backend.logging_config import configure_logging, IST_TZ
from ..settings import PORT
from .middleware import RequestLimitingMiddleware, StructuredLoggingMiddleware
from .mobile_middleware import MobileStateMiddleware
from .power_middleware import PowerMiddleware
from .routers import commands, context_events, drive_index, file_memories, mobile_compute, satellite

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from ..settings import LLM_MODEL, LLM_BUDGET_PROFILE, RATE_LIMIT_PER_USER_PER_MINUTE
    from .spend_policy import OPENROUTER_DAILY_BUDGET_USD
    logger.info("Jarvis processing API started | port=%s | model=%s | storage=request SQLite RAM", PORT, LLM_MODEL)
    logger.info("AI allowance $%.2f/day | %s requests/min | profile=%s",
                OPENROUTER_DAILY_BUDGET_USD, RATE_LIMIT_PER_USER_PER_MINUTE, LLM_BUDGET_PROFILE)
    yield
    logger.info("Jarvis processing API stopped")


async def health_check() -> dict:
    from ..settings import LLM_BUDGET_PROFILE, MAX_DAILY_LLM_CALLS, MAX_DAILY_TOKENS, RATE_LIMIT_PER_USER_PER_MINUTE
    from .spend_policy import OPENROUTER_DAILY_BUDGET_USD
    return {
        "status": "healthy", "service": "jarvis-processing-api", "mode": "mobile",
        "timestamp": datetime.now(IST_TZ).isoformat(), "timezone": "IST (Asia/Kolkata)",
        "database": {"status": "healthy", "engine": "sqlite"},
        "storage": {"backend": "mobile-only", "mobile_is_authoritative": True,
                    "server_storage": "request-memory", "document_index": "existing-chroma"},
        "ai_budget": {"profile": LLM_BUDGET_PROFILE, "daily_tokens": MAX_DAILY_TOKENS or None,
                      "daily_calls": MAX_DAILY_LLM_CALLS or None, "daily_budget_usd": OPENROUTER_DAILY_BUDGET_USD,
                      "requests_per_minute": RATE_LIMIT_PER_USER_PER_MINUTE, "reset_timezone": "Asia/Kolkata"},
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Jarvis Processing API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(RequestLimitingMiddleware)
    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(PowerMiddleware)
    compute = APIRouter()
    compute.routes.extend(route for route in commands.router.routes if getattr(route, 'path', '').startswith('/commands/'))
    compute.routes.extend(route for route in context_events.router.routes if getattr(route, 'path', '') == '/context-events')
    compute.routes.extend(route for route in file_memories.router.routes if getattr(route, 'path', '').endswith('/analyze'))
    allowed_index = {'/drive-index/status', '/drive-index/search', '/drive-index/search-contents',
                     '/drive-index/evidence', '/drive-index/files/{file_id}'}
    compute.routes.extend(route for route in drive_index.router.routes if getattr(route, 'path', '') in allowed_index)
    app.include_router(compute)
    app.include_router(mobile_compute.router)
    app.include_router(satellite.router)
    app.add_middleware(MobileStateMiddleware)
    app.add_api_route('/', health_check, methods=['GET'], tags=['monitoring'])
    app.add_api_route('/health', health_check, methods=['GET'], tags=['monitoring'])
    return app


app = create_app()


def run() -> None:
    uvicorn.run('src.api.main:app', host='0.0.0.0', port=PORT, reload=True,
                reload_dirs=['src'], reload_excludes=['*.db', '*.db-*', 'data/*', 'logs/*', '*.log'])


if __name__ == '__main__':
    run()
