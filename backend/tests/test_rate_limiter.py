"""
Unit tests for TokenBudgetGuard and rate limiter.
"""

import pytest
from fastapi import HTTPException

from src.api.rate_limiter import TokenBudgetGuard


def test_token_budget_guard_sliding_window():
    guard = TokenBudgetGuard()
    user_id = "test_user_rate"

    # Should allow up to RATE_LIMIT_PER_USER_PER_MINUTE calls
    for _ in range(15):
        guard.check_request_rate(user_id)

    # 16th call within the same minute should raise 429
    with pytest.raises(HTTPException) as exc_info:
        guard.check_request_rate(user_id)
    assert exc_info.value.status_code == 429


def test_token_budget_guard_caching():
    guard = TokenBudgetGuard()
    key = guard.compute_cache_key("test", "remind me to check oil")

    assert guard.get_cached_response(key) is None

    mock_resp = {"status": "ok", "message": "created reminder"}
    guard.store_cached_response(key, mock_resp)

    cached = guard.get_cached_response(key)
    assert cached == mock_resp


def test_token_budget_guard_token_reservation():
    guard = TokenBudgetGuard()
    user_id = "test_user_tokens"

    # Normal token reservation succeeds
    guard.check_and_reserve_tokens(user_id, estimated_input_tokens=500)

    # Consuming excessive tokens exceeding daily limit raises 429
    with pytest.raises(HTTPException) as exc_info:
        guard.check_and_reserve_tokens(user_id, estimated_input_tokens=200_000)
    assert exc_info.value.status_code == 429
