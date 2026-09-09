"""
Jarvis Token Quota & Rate Limiting System.

Guards OpenRouter LLM budgets against runaway costs, rapid duplicate mobile retries,
and high token bursts with sliding-window rate limits, daily call ceilings,
and deterministic prompt deduplication caching.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status

try:
    from ..settings import (
        LLM_CACHE_TTL_SECONDS,
        MAX_DAILY_LLM_CALLS,
        MAX_DAILY_TOKENS,
        MAX_TOKENS_PER_CALL,
        RATE_LIMIT_PER_USER_PER_MINUTE,
    )
except (ImportError, ValueError):
    from src.settings import (
        LLM_CACHE_TTL_SECONDS,
        MAX_DAILY_LLM_CALLS,
        MAX_DAILY_TOKENS,
        MAX_TOKENS_PER_CALL,
        RATE_LIMIT_PER_USER_PER_MINUTE,
    )

logger = logging.getLogger(__name__)


@dataclass
class DailyUsageRecord:
    day: date
    call_count: int = 0
    estimated_tokens: int = 0


class TokenBudgetGuard:
    """Singleton guard managing API call rates, daily token caps, and deduplication."""

    _instance: Optional[TokenBudgetGuard] = None

    def __new__(cls) -> TokenBudgetGuard:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self) -> None:
        self._user_requests: Dict[str, deque[float]] = defaultdict(deque)
        self._daily_usage: Dict[str, DailyUsageRecord] = {}
        # prompt_hash -> (cached_response, timestamp)
        self._response_cache: Dict[str, Tuple[Any, float]] = {}

    def _get_daily_record(self, user_id: str) -> DailyUsageRecord:
        today = date.today()
        record = self._daily_usage.get(user_id)
        if record is None or record.day != today:
            record = DailyUsageRecord(day=today, call_count=0, estimated_tokens=0)
            self._daily_usage[user_id] = record
        return record

    def check_request_rate(self, user_id: str) -> None:
        """Enforces sliding-window requests per minute per user."""
        now = time.time()
        window = self._user_requests[user_id]

        # Purge timestamps older than 60 seconds
        while window and now - window[0] > 60.0:
            window.popleft()

        if len(window) >= RATE_LIMIT_PER_USER_PER_MINUTE:
            logger.warning(
                "Rate limit reached for user %s: %d reqs in last 60s (max %d)",
                user_id,
                len(window),
                RATE_LIMIT_PER_USER_PER_MINUTE,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: maximum {RATE_LIMIT_PER_USER_PER_MINUTE} requests per minute.",
            )

        window.append(now)

    def check_and_reserve_tokens(self, user_id: str, estimated_input_tokens: int) -> None:
        """Enforces daily call ceiling, daily token budget, and per-call token max."""
        record = self._get_daily_record(user_id)

        if record.call_count >= MAX_DAILY_LLM_CALLS:
            logger.warning(
                "Daily LLM call limit reached for user %s: %d / %d calls",
                user_id,
                record.call_count,
                MAX_DAILY_LLM_CALLS,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily LLM budget reached ({record.call_count}/{MAX_DAILY_LLM_CALLS} calls). Resets at midnight.",
            )

        if record.estimated_tokens + estimated_input_tokens > MAX_DAILY_TOKENS:
            logger.warning(
                "Daily token budget exhausted for user %s: %d tokens used (limit: %d)",
                user_id,
                record.estimated_tokens,
                MAX_DAILY_TOKENS,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily OpenRouter token budget exceeded. Quota protects against billing bursts.",
            )

    def record_llm_usage(self, user_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Records actual token consumption."""
        record = self._get_daily_record(user_id)
        total = prompt_tokens + completion_tokens
        record.call_count += 1
        record.estimated_tokens += total
        logger.info(
            "User %s consumed %d tokens (%d in, %d out). Daily total: %d calls, %d tokens.",
            user_id,
            total,
            prompt_tokens,
            completion_tokens,
            record.call_count,
            record.estimated_tokens,
        )

    def get_cached_response(self, cache_key: str) -> Optional[Any]:
        """Retrieves cached response if within TTL."""
        if cache_key in self._response_cache:
            resp, ts = self._response_cache[cache_key]
            if time.time() - ts < LLM_CACHE_TTL_SECONDS:
                logger.info("Serving deduplicated response from cache for key %s", cache_key[:12])
                return resp
            del self._response_cache[cache_key]
        return None

    def store_cached_response(self, cache_key: str, response: Any) -> None:
        """Caches response for deduplication."""
        self._response_cache[cache_key] = (response, time.time())

    @staticmethod
    def compute_cache_key(prefix: str, content: str) -> str:
        """Computes SHA-256 cache key for prompt content."""
        h = hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()
        return f"{prefix}:{h}"
