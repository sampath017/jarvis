"""
Jarvis Context-Aware Mobile Agent — Central Configuration

Loads environment variables from .env and provides typed access
for all backend settings.
"""

from __future__ import annotations
from .budget_profiles import budget_limits

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ── Local Database & Paths ───────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent
# Explicit isolated repository test path. API requests always use
# a temporary RAM database and never open this path.
LOCAL_DB_PATH: Path = Path(
    os.getenv("JARVIS_LOCAL_DB_PATH", str(
        BASE_DIR / "data" / "jarvis_local.db"))
)

# ── Google Places API (New) ─────────────────────────────────────────────────
GOOGLE_PLACES_API_KEY: str = "".join(
    os.getenv("GOOGLE_PLACES_API_KEY", "").split()).strip()
PLACES_DAILY_BUDGET_PER_USER = 50

# ── LLM Configuration ──────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = "".join(
    os.getenv("OPENROUTER_API_KEY", "").split()).strip()
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
LLM_MODEL: str = os.getenv("LLM_MODEL", "z-ai/glm-5.3-flash")
OPENROUTER_TEMPERATURE: float = 0.1
OPENROUTER_MODEL_MULTIMODAL: str = os.getenv(
    "OPENROUTER_MODEL_MULTIMODAL", LLM_MODEL)
OPENROUTER_MODEL_PDF: str = os.getenv(
    "OPENROUTER_MODEL_PDF", "google/gemini-3.8-flash")
AGENT_MAX_ITERATIONS = 50
# ── OpenRouter Daily Budget (USD) ───────────────────────────────────────────
OPENROUTER_DAILY_BUDGET_USD = 0.50

# ── LangSmith Observability ─────────────────────────────────────────────────
# Phone content stays out of external trace storage.
LANGCHAIN_TRACING_V2: str = 'false'
os.environ["LANGSMITH_TRACING"] = LANGCHAIN_TRACING_V2
os.environ["LANGCHAIN_TRACING_V2"] = LANGCHAIN_TRACING_V2
LANGCHAIN_API_KEY: str = os.getenv(
    "LANGCHAIN_API_KEY", os.getenv("LANGSMITH_API_KEY", "")).strip()
LANGCHAIN_PROJECT: str = os.getenv(
    "LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "Jarvis")).strip()

# LangChain's current tracing variables use the LANGSMITH prefix, while some
# installed versions still read the LANGCHAIN names.  Support both without
# overwriting explicit environment configuration supplied by the developer.
if LANGCHAIN_TRACING_V2.lower() == "true":
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if LANGCHAIN_API_KEY:
        os.environ.setdefault("LANGSMITH_API_KEY", LANGCHAIN_API_KEY)
        os.environ.setdefault("LANGCHAIN_API_KEY", LANGCHAIN_API_KEY)
    if LANGCHAIN_PROJECT:
        os.environ.setdefault("LANGSMITH_PROJECT", LANGCHAIN_PROJECT)
        os.environ.setdefault("LANGCHAIN_PROJECT", LANGCHAIN_PROJECT)

# ── Session State Machine ──────────────────────────────────────────────────
SESSION_TTL_SEC: int = 1800             # 30-minute TTL for paused sessions
# Max distance from parking to maintain session
PARKING_RADIUS_M: float = 1000.0
MIN_DWELL_SEC: float = 60.0            # Minimum dwell time to qualify as a "stop"
MAX_SPEED_WALKING_MPS: float = 2.0     # Max speed (m/s) considered walking

# ── Conflict Resolution (context assessment) ───────────────────────────────────────────
CONFLICT_CONFIDENCE_THRESHOLD: float = 0.6
GPS_ACCURACY_POOR_M: float = 50.0
VEHICLE_HIGH_CONFIDENCE_THRESHOLD: float = 0.75
CONTEXT_SESSION_PROMOTION_THRESHOLD: float = 0.75

# ── API Server ──────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── Rate Limiting & Token Budget Guards ───────────────────────────────────────
_budget_limits = budget_limits()
LLM_BUDGET_PROFILE: str = _budget_limits.profile
RATE_LIMIT_PER_USER_PER_MINUTE: int = _budget_limits.requests_per_minute
MAX_DAILY_LLM_CALLS: int = _budget_limits.daily_calls

# Max output tokens per call (allows full structured JSON schemas without truncation)
MAX_TOKENS_PER_CALL: int = 2048

# Reasoning and the final answer share the provider's completion allowance.
# An 8k ceiling exhausted the reasoning budget and forced a complete retry.
LLM_OUTPUT_TOKENS: int = max(2048, min(32768, int(os.getenv("LLM_OUTPUT_TOKENS", "16384"))))

# Enforced max token generation per call in OpenRouter
OPENROUTER_MAX_TOKENS: int = MAX_TOKENS_PER_CALL
MAX_DAILY_TOKENS: int = _budget_limits.daily_tokens

# 5-minute cache to deduplicate duplicate mobile requests
LLM_CACHE_TTL_SECONDS: int = 300
MAX_REQUEST_SIZE_BYTES: int = 65536           # 65 KB max payload size
NOTIFICATION_SWEEP_SECONDS: float = 30.0
