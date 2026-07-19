"""
API Configuration settings.

Loads configuration from environment variables or .env file using pydantic-settings.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """Production Settings for Jarvis FastAPI backend."""

    # ── Firebase ─────────────────────────────────────────────────────────────
    firebase_project_id: str = ""

    # ── API Server ───────────────────────────────────────────────────────────
    port: int = 8080
    log_level: str = "INFO"
    # "enforce" or "monitor" (soft enforcement)
    app_check_mode: str = "monitor"

    # ── Rate Limiting & Safety ───────────────────────────────────────────────
    rate_limit_per_user_per_minute: int = 30
    max_request_size_bytes: int = 65536  # 64 KB limit

    # settings load
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global settings instance
settings = APISettings()
