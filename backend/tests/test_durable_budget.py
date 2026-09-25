from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from threading import RLock
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from src.api import rate_limiter as limiter


def fresh_guard():
    guard = object.__new__(limiter.TokenBudgetGuard)
    guard._init_state()
    return guard


@pytest.fixture
def cloud(monkeypatch):
    from google.cloud import firestore
    from src.services import firestore_service
    state, lock = {}, RLock()
    class Ref:
        def __init__(self, path=''): self.path = path
        def collection(self, name): return Ref(self.path + '/' + name)
        def document(self, name): return Ref(self.path + '/' + name)
        def get(self, **kwargs):
            return SimpleNamespace(to_dict=lambda: deepcopy(state.get(self.path)))
    class Transaction:
        def set(self, ref, value): state[ref.path] = deepcopy(value)
    db = Ref()
    db.transaction = Transaction
    def transactional(function):
        def run(transaction):
            with lock: return function(transaction)
        return run
    monkeypatch.setattr(firestore, 'transactional', transactional)
    monkeypatch.setattr(firestore_service, 'FirestoreService', lambda: SimpleNamespace(_db=db))
    monkeypatch.setenv('K_SERVICE', 'jarvis-backend')
    monkeypatch.setattr(limiter, 'MAX_DAILY_TOKENS', 0)
    monkeypatch.setattr(limiter, 'MAX_DAILY_LLM_CALLS', 0)
    return state


def test_instances_share_holds_and_actual_usage_after_restart(cloud, monkeypatch):
    monkeypatch.setattr(limiter, 'MAX_DAILY_TOKENS', 1000)
    first, second = fresh_guard(), fresh_guard()
    receipt = first.check_and_reserve_tokens('u', 800)
    with pytest.raises(HTTPException): second.check_and_reserve_tokens('u', 300)
    second.record_llm_usage('u', 100, 50, reservation=receipt)
    restarted = fresh_guard()
    assert restarted._get_daily_record('u').estimated_tokens == 150
    restarted.record_llm_usage('u', 100, 50, reservation=receipt)
    assert restarted._get_daily_record('u').estimated_tokens == 150
    restarted.check_and_reserve_tokens('u', 850)
    assert restarted._get_daily_record('u').call_count == 2


def test_concurrent_instances_cannot_overbook(cloud, monkeypatch):
    monkeypatch.setattr(limiter, 'MAX_DAILY_TOKENS', 1000)
    def reserve(_):
        try:
            fresh_guard().check_and_reserve_tokens('u', 600)
            return True
        except HTTPException: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


def test_settlement_stays_on_start_day_across_midnight(cloud, monkeypatch):
    monkeypatch.setattr(limiter, 'budget_day', lambda: date(2026, 10, 6))
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1000)
    monkeypatch.setattr(limiter, 'budget_day', lambda: date(2026, 10, 7))
    guard.record_llm_usage('u', 100, 20, reservation=receipt)
    assert guard._get_daily_record('u').estimated_tokens == 0
    assert cloud['/users/u/ai_usage/2026-10-06']['estimated_tokens'] == 120


def test_storage_outage_never_falls_back_to_empty_quota(cloud, monkeypatch):
    from src.services import firestore_service
    monkeypatch.setattr(firestore_service, 'FirestoreService', lambda: SimpleNamespace(_db=None))
    with pytest.raises(HTTPException) as error:
        fresh_guard().check_and_reserve_tokens('u', 100)
    assert error.value.status_code == 503


def test_unfinished_provider_request_keeps_hold(cloud):
    guard = fresh_guard()
    guard.check_and_reserve_tokens('u', 1000)
    assert fresh_guard()._get_daily_record('u').estimated_tokens == 1000


def test_call_limit_counts_inflight_calls(cloud, monkeypatch):
    monkeypatch.setattr(limiter, 'MAX_DAILY_LLM_CALLS', 1)
    fresh_guard().check_and_reserve_tokens('u', 100)
    with pytest.raises(HTTPException) as error:
        fresh_guard().check_and_reserve_tokens('u', 100)
    assert 'call allowance' in error.value.detail


def test_money_cap_counts_all_tokens_without_a_token_ceiling(cloud):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1_100_000)
    guard.record_llm_usage('u', 1_100_000, 0, reservation=receipt, cost_usd='0.165')
    assert guard._get_daily_record('u').estimated_tokens == 1_100_000
    with pytest.raises(HTTPException) as error:
        guard.check_and_reserve_tokens('u', 300_000)
    assert 'Rs 20 daily AI allowance' in error.value.detail
    assert f'Rs {limiter.rupees(limiter.DAILY_BUDGET_NANOS - 165_000_000):.2f}' in error.value.detail
    assert 'not an OpenRouter' in error.value.detail


def test_actual_provider_cost_releases_money_hold_once(cloud):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 10000, max_output_tokens=4000)
    guard.record_llm_usage('u', 1000, 100, reservation=receipt, cost_usd='0.0002')
    guard.record_llm_usage('u', 1000, 100, reservation=receipt, cost_usd='0.0002')
    assert guard._get_daily_record('u').cost_nanos == 200_000


def test_missing_billing_data_keeps_conservative_money_hold(cloud):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 10000, max_output_tokens=4000)
    before = guard._get_daily_record('u').cost_nanos
    guard.record_llm_usage('u', 10, 1, reservation=receipt)
    assert guard._get_daily_record('u').cost_nanos == before


def test_all_models_share_daily_spending_allowance(cloud):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1_000_000)
    guard.record_llm_usage('u', 1_000_000, 0, reservation=receipt, cost_usd='0.15')
    with pytest.raises(HTTPException):
        fresh_guard().check_and_reserve_tokens('u', 100_000, model='google/gemini-3.8-flash')


def test_money_holds_prevent_parallel_overspending(cloud):
    def reserve(_):
        try:
            fresh_guard().check_and_reserve_tokens('u', 1_000_000)
            return True
        except HTTPException: return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1


def test_invalid_or_negative_provider_cost_cannot_refund_hold(cloud):
    for bad in ('NaN', '-1', 'invalid'):
        guard = fresh_guard()
        receipt = guard.check_and_reserve_tokens(bad, 1000)
        guard.record_llm_usage(bad, 10, 1, reservation=receipt, cost_usd=bad)
        assert guard._get_daily_record(bad).cost_nanos == 150_000


def test_status_read_never_creates_or_rewrites_ledger(cloud):
    guard = fresh_guard()
    assert guard._get_daily_record('unseen').cost_nanos == 0
    assert not cloud
    receipt = guard.check_and_reserve_tokens('u', 1000)
    before = deepcopy(cloud)
    guard._get_daily_record('u')
    assert cloud == before


def test_accounting_preserves_migration_marker(cloud):
    day = limiter.budget_day().isoformat()
    cloud[f'/users/u/ai_usage/{day}'] = {'migration_id': 'old-ledger', 'cost_nanos': 123}
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1000)
    guard.record_llm_usage('u', 10, 10, reservation=receipt, cost_usd='0.00001')
    assert cloud[f'/users/u/ai_usage/{day}']['migration_id'] == 'old-ledger'
    assert guard._get_daily_record('u').cost_nanos == 10123


def test_timing_is_logged_even_when_reservation_rejected(cloud, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger=limiter.__name__):
        with pytest.raises(HTTPException):
            fresh_guard().check_and_reserve_tokens('u', 100_000_000)
    assert 'AI budget timing operation=reserve backend=firestore latency_ms=' in caplog.text
