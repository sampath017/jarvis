"""
Jarvis Token Quota & Rate Limiting System.

Guards OpenRouter LLM budgets against runaway costs, rapid duplicate mobile retries,
and high token bursts with sliding-window rate limits, daily call ceilings,
and deterministic prompt deduplication caching.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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

from .spend_policy import DAILY_BUDGET_NANOS, token_cost_nanos, reported_cost_nanos, rupees
from ..settings import OPENROUTER_MODEL_TIER2

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def budget_day() -> date:
    return datetime.now(IST).date()


@dataclass
class DailyUsageRecord:
    day: date
    call_count: int = 0
    estimated_tokens: int = 0
    reservations: dict[str, dict] = field(default_factory=dict)
    cost_nanos: int = 0


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
        self._daily_usage: dict[tuple[str, date], DailyUsageRecord] = {}
        self._usage_lock = threading.RLock()
        # prompt_hash -> (cached_response, timestamp)
        self._response_cache: Dict[str, Tuple[Any, float]] = {}

    def _mutate_usage(self, user_id, day, operation):
        started = time.perf_counter()
        try:
            return self._mutate_usage_impl(user_id, day, operation)
        finally:
            logger.info("AI budget timing operation=%s backend=%s latency_ms=%.2f",
                        operation.__name__,
                        "firestore" if os.getenv("K_SERVICE") or os.getenv("K_REVISION") else "memory",
                        (time.perf_counter() - started) * 1000)

    def _mutate_usage_impl(self, user_id, day, operation):
        # Cloud Run instances must share one ledger. Never fall back to memory
        # when durable storage is unavailable: that would silently reset quota.
        if os.getenv("K_SERVICE") or os.getenv("K_REVISION"):
            from google.cloud import firestore
            from ..services.firestore_service import FirestoreService
            try:
                db = FirestoreService()._db
                if db is None:
                    raise RuntimeError("Budget storage unavailable")
                ref = db.collection("users").document(user_id).collection("ai_usage").document(day.isoformat())

                @firestore.transactional
                def update(transaction):
                    data = ref.get(transaction=transaction).to_dict() or {}
                    record = DailyUsageRecord(day, data.get("call_count", 0),
                                              data.get("estimated_tokens", 0),
                                              dict(data.get("reservations", {})), data.get("cost_nanos", 0))
                    result = operation(record)
                    transaction.set(ref, {**data, "call_count": record.call_count,
                        "estimated_tokens": record.estimated_tokens,
                        "reservations": record.reservations, "cost_nanos": record.cost_nanos,
                        "updated_at": datetime.now(timezone.utc)})
                    return result
                return update(db.transaction())
            except HTTPException:
                raise
            except Exception as exc:
                logger.exception("AI budget storage unavailable")
                raise HTTPException(503, "Jarvis could not check its AI allowance. Please retry shortly; this is not a daily limit or a provider-credit error.") from exc
        with self._usage_lock:
            key = (user_id, day)
            record = self._daily_usage.setdefault(key, DailyUsageRecord(day))
            return operation(record)

    def _get_daily_record(self, user_id: str) -> DailyUsageRecord:
        """Read status without starting a transaction or rewriting the ledger."""
        day = budget_day()
        if os.getenv("K_SERVICE") or os.getenv("K_REVISION"):
            from ..services.firestore_service import FirestoreService
            try:
                db = FirestoreService()._db
                if db is None:
                    raise RuntimeError("Budget storage unavailable")
                data = (db.collection("users").document(user_id).collection("ai_usage")
                        .document(day.isoformat()).get().to_dict()) or {}
                return DailyUsageRecord(day, data.get("call_count", 0),
                    data.get("estimated_tokens", 0), dict(data.get("reservations", {})),
                    data.get("cost_nanos", 0))
            except Exception as exc:
                raise HTTPException(503, "Jarvis could not read its AI allowance. Please retry shortly.") from exc
        with self._usage_lock:
            return self._daily_usage.get((user_id, day), DailyUsageRecord(day))

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

    def check_and_reserve_tokens(self, user_id: str, estimated_input_tokens: int, *, model=OPENROUTER_MODEL_TIER2, max_output_tokens=0) -> tuple[date, str]:
        """Atomically hold input + maximum output before a paid call starts."""
        amount = max(0, int(estimated_input_tokens))
        cost = token_cost_nanos(model, max(0, amount - max_output_tokens), max_output_tokens)
        day, reservation_id = budget_day(), secrets.token_hex(16)
        reset = f"{day + timedelta(days=1):%d %b %Y} at 12:00 AM IST"

        def reserve(record):
            available = max(0, DAILY_BUDGET_NANOS - record.cost_nanos)
            if cost > available:
                detail = (f"Jarvis has about Rs {rupees(available):.2f} left in its Rs 20 daily AI allowance, "
                          f"but this request needs an estimated reservation of Rs {rupees(cost):.2f}. "
                          "This is the app's spending allowance, not an OpenRouter credit error. ")
                if cost > DAILY_BUDGET_NANOS:
                    detail += "This request exceeds a full day's allowance. Shorten the conversation or file request; waiting for reset will not make it fit."
                else:
                    detail += f"A cheaper request may still work. The allowance resets on {reset}. Running requests may release unused reservations sooner."
                raise HTTPException(429, detail)
            if MAX_DAILY_LLM_CALLS and record.call_count >= MAX_DAILY_LLM_CALLS:
                raise HTTPException(429, f"Jarvis's own daily AI call allowance is used or reserved ({MAX_DAILY_LLM_CALLS} calls). It resets on {reset}. This is a Jarvis app limit, not an OpenRouter credit error.")
            remaining = max(0, MAX_DAILY_TOKENS - record.estimated_tokens)
            if MAX_DAILY_TOKENS and amount > remaining:
                logger.warning("AI allowance cannot fit request user=%s used_or_reserved=%d requested=%d limit=%d",
                               user_id, record.estimated_tokens, amount, MAX_DAILY_TOKENS)
                detail = (f"Jarvis has {remaining:,} of {MAX_DAILY_TOKENS:,} daily AI tokens available, "
                          f"but this request needs an estimated allowance of {amount:,} including maximum reply capacity. "
                          "This is Jarvis's app limit, not an OpenRouter credit error. ")
                if amount > MAX_DAILY_TOKENS:
                    detail += "This request exceeds the entire daily allowance; waiting for reset will not make it fit. Shorten the conversation or file request."
                else:
                    detail += f"A smaller request may still work. The daily allowance resets on {reset}; capacity reserved by running requests may return sooner."
                raise HTTPException(429, detail)
            record.call_count += 1
            record.estimated_tokens += amount
            record.cost_nanos += cost
            record.reservations[reservation_id] = {"tokens": amount, "cost_nanos": cost, "model": model}
            return day, reservation_id
        return self._mutate_usage(user_id, day, reserve)

    def record_llm_usage(self, user_id: str, prompt_tokens: int, completion_tokens: int, *, reservation=None, cost_usd=None, model=OPENROUTER_MODEL_TIER2) -> None:
        """Settle a hold once using actual usage, against the day it started."""
        total = max(0, int(prompt_tokens)) + max(0, int(completion_tokens))
        day = reservation[0] if reservation else budget_day()

        def settle(record):
            if reservation:
                held = record.reservations.pop(reservation[1], None)
                if held is None:
                    return  # A repeated acknowledgement must not charge twice.
                record.estimated_tokens += total - held['tokens']
                actual_cost = reported_cost_nanos(cost_usd)
                if actual_cost is None:
                    # Without authoritative billing data never undercount usage.
                    actual_cost = max(held['cost_nanos'], token_cost_nanos(held['model'], prompt_tokens, completion_tokens))
                record.cost_nanos += actual_cost - held['cost_nanos']
            else:
                record.call_count += 1
                record.estimated_tokens += total
                actual_cost = reported_cost_nanos(cost_usd)
                record.cost_nanos += actual_cost if actual_cost is not None else token_cost_nanos(model, prompt_tokens, completion_tokens)
            logger.info("User %s consumed %d tokens (%d in, %d out). Daily total: %d calls, %d tokens.",
                        user_id, total, prompt_tokens, completion_tokens,
                        record.call_count, record.estimated_tokens)
        self._mutate_usage(user_id, day, settle)

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
