"""
Unit tests for TokenBudgetGuard and rate limiter.
"""

import pytest
from fastapi import HTTPException

from src.api.rate_limiter import TokenBudgetGuard
from src.api import rate_limiter as limiter


@pytest.fixture(autouse=True)
def isolated_guard(monkeypatch):
    monkeypatch.delenv('K_SERVICE', raising=False)
    monkeypatch.delenv('K_REVISION', raising=False)
    monkeypatch.setattr(limiter, 'MAX_DAILY_TOKENS', 150_000)
    monkeypatch.setattr(limiter, 'MAX_DAILY_LLM_CALLS', 150)
    monkeypatch.setattr(limiter, 'DAILY_BUDGET_NANOS', 100_000_000_000)
    TokenBudgetGuard()._init_state()


def test_token_budget_guard_sliding_window():
    guard = TokenBudgetGuard()
    user_id = "test_user_rate"

    # Should allow up to RATE_LIMIT_PER_USER_PER_MINUTE calls
    for _ in range(limiter.RATE_LIMIT_PER_USER_PER_MINUTE):
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
        guard.check_and_reserve_tokens(user_id, estimated_input_tokens=limiter.MAX_DAILY_TOKENS + 1)
    assert exc_info.value.status_code == 429


def test_budget_message_distinguishes_remaining_capacity_and_oversized_request():
    guard = TokenBudgetGuard()
    guard.record_llm_usage('partial', limiter.MAX_DAILY_TOKENS - 1000, 0)
    with pytest.raises(HTTPException) as error:
        guard.check_and_reserve_tokens('partial', 2000)
    assert '1,000' in error.value.detail
    assert 'smaller request may still work' in error.value.detail
    assert '12:00 AM IST' in error.value.detail
    assert 'not an OpenRouter credit error' in error.value.detail
    guard.check_and_reserve_tokens('partial', 500)
    with pytest.raises(HTTPException) as error:
        guard.check_and_reserve_tokens('oversized', limiter.MAX_DAILY_TOKENS + 1)
    assert 'waiting for reset will not make it fit' in error.value.detail


def test_daily_budget_resets_on_ist_day_boundary(monkeypatch):
    from datetime import date
    guard = TokenBudgetGuard()
    monkeypatch.setattr(limiter, 'budget_day', lambda: date(2026, 10, 4))
    guard.record_llm_usage('test_ist_reset', 100, 20)
    assert guard._get_daily_record('test_ist_reset').estimated_tokens == 120
    monkeypatch.setattr(limiter, 'budget_day', lambda: date(2026, 10, 5))
    assert guard._get_daily_record('test_ist_reset').estimated_tokens == 0


def test_local_testing_profile_is_finite_and_higher():
    from src.budget_profiles import budget_limits, PRODUCTION_LIMITS
    test = budget_limits({'JARVIS_BUDGET_PROFILE': 'testing'})
    assert test.profile == 'testing'
    assert PRODUCTION_LIMITS.daily_tokens == PRODUCTION_LIMITS.daily_calls == 0
    assert test.daily_tokens == 3_000_000
    assert test.daily_calls == 2_000 and test.requests_per_minute == 120


@pytest.mark.parametrize('marker', ['K_SERVICE', 'K_REVISION'])
def test_cloud_run_forces_production_even_with_testing_config(marker):
    from src.budget_profiles import budget_limits, PRODUCTION_LIMITS
    assert budget_limits({marker: 'jarvis-backend', 'JARVIS_BUDGET_PROFILE': 'testing', 'ENVIRONMENT': 'testing'}) == PRODUCTION_LIMITS


@pytest.mark.parametrize('config', [{}, {'JARVIS_BUDGET_PROFILE': 'unknown'}, {'JARVIS_BUDGET_PROFILE': 'production', 'ENVIRONMENT': 'testing'}])
def test_unspecified_or_invalid_profile_keeps_production_limits(config):
    from src.budget_profiles import budget_limits, PRODUCTION_LIMITS
    assert budget_limits(config) == PRODUCTION_LIMITS
