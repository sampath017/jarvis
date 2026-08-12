"""
Jarvis Context-Aware Mobile Agent — Central Configuration

Loads environment variables from .env and provides typed access
for all backend settings.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ── Local Database & Paths ───────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent
# Tests and local simulator runs can isolate their data without changing a
# developer's normal local database. Production defaults to backend/data.
LOCAL_DB_PATH: Path = Path(
    os.getenv("JARVIS_LOCAL_DB_PATH", str(BASE_DIR / "data" / "jarvis_local.db"))
)

# ── Google Places API (New) ─────────────────────────────────────────────────
GOOGLE_PLACES_API_KEY: str = "".join(
    os.getenv("GOOGLE_PLACES_API_KEY", "").split()).strip()
PLACES_DAILY_BUDGET_PER_USER = 50

# ── LLM Configuration ──────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = "".join(
    os.getenv("OPENROUTER_API_KEY", "").split()).strip()
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_TIER1: str = os.getenv(
    "OPENROUTER_MODEL_TIER1", "qwen/qwen-2.5-7b-instruct")
OPENROUTER_MODEL_TIER2: str = os.getenv(
    "OPENROUTER_MODEL_TIER2", "qwen/qwen-2.5-72b-instruct")
OPENROUTER_MAX_TOKENS: int = 1024
OPENROUTER_TEMPERATURE: float = 0.1

# ── LangSmith Observability ─────────────────────────────────────────────────
LANGCHAIN_TRACING_V2: str = os.getenv(
    "LANGCHAIN_TRACING_V2", os.getenv("LANGSMITH_TRACING", "false")).strip()
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

# ── Conflict Resolution (Tier 1) ───────────────────────────────────────────
CONFLICT_CONFIDENCE_THRESHOLD: float = 0.6
GPS_ACCURACY_POOR_M: float = 50.0
VEHICLE_HIGH_CONFIDENCE_THRESHOLD: float = 0.75
TIER1_SESSION_PROMOTION_THRESHOLD: float = 0.75

# ── API Server ──────────────────────────────────────────────────────────────
PORT = 8080
LOG_LEVEL = "INFO"
APP_CHECK_MODE = "monitor"

# ── Rate Limiting ───────────────────────────────────────────────────────────
RATE_LIMIT_PER_USER_PER_MINUTE = 30
MAX_REQUEST_SIZE_BYTES = 65536  # 65 kilo bytes
NOTIFICATION_SWEEP_SECONDS: float = float(os.getenv("NOTIFICATION_SWEEP_SECONDS", "30"))
