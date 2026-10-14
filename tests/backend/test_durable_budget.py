from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from src.api import rate_limiter as limiter


def fresh_guard():
    guard = object.__new__(limiter.TokenBudgetGuard)
    guard._init_state()
    return guard


@pytest.fixture
def ledger(monkeypatch):
    from src.services.sqlite_store import SqlStore
    from src.services import record_store
    from src.services.runtime_power import RuntimePower
    store = SqlStore(':memory:')
    monkeypatch.setattr(record_store, 'RecordStore', lambda: SimpleNamespace(sql=store))
    monkeypatch.setattr(RuntimePower, 'store', lambda _: store)
    monkeypatch.setattr(RuntimePower, '_instance', None)
    monkeypatch.setattr(limiter, 'MAX_DAILY_TOKENS', 0)
    monkeypatch.setattr(limiter, 'MAX_DAILY_LLM_CALLS', 0)
    yield store
    store.db.close()


def test_instances_share_holds_and_actual_usage_after_restart(ledger, monkeypatch):
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


def test_concurrent_instances_cannot_overbook(ledger, monkeypatch):
    monkeypatch.setattr(limiter, 'MAX_DAILY_TOKENS', 1000)
    def reserve(_):
        try:
            fresh_guard().check_and_reserve_tokens('u', 600)
            return True
        except HTTPException: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


def test_settlement_stays_on_start_day_across_midnight(ledger, monkeypatch):
    monkeypatch.setattr(limiter, 'budget_day', lambda: date(2026, 10, 6))
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1000)
    monkeypatch.setattr(limiter, 'budget_day', lambda: date(2026, 10, 7))
    guard.record_llm_usage('u', 100, 20, reservation=receipt)
    assert guard._get_daily_record('u').estimated_tokens == 0
    assert ledger.get('ai_usage', '2026-10-06', uid='u')['estimated_tokens'] == 120


def test_storage_outage_never_falls_back_to_empty_quota(ledger, monkeypatch):
    from src.services import record_store
    monkeypatch.setattr(record_store, 'RecordStore', lambda: SimpleNamespace(sql=None))
    with pytest.raises(HTTPException) as error:
        fresh_guard().check_and_reserve_tokens('u', 100)
    assert error.value.status_code == 503


def test_sql_power_off_prevents_a_new_spending_hold(ledger):
    ledger.put('runtime_control', 'jarvis', {'enabled': False, 'cloud_ready': True})
    with pytest.raises(HTTPException) as error:
        fresh_guard().check_and_reserve_tokens('u', 100)
    assert error.value.status_code == 503
    assert 'powered off' in error.value.detail
    assert ledger.list('ai_usage') == []


def test_unfinished_provider_request_keeps_hold(ledger):
    guard = fresh_guard()
    guard.check_and_reserve_tokens('u', 1000)
    assert fresh_guard()._get_daily_record('u').estimated_tokens == 1000


def test_call_limit_counts_inflight_calls(ledger, monkeypatch):
    monkeypatch.setattr(limiter, 'MAX_DAILY_LLM_CALLS', 1)
    fresh_guard().check_and_reserve_tokens('u', 100)
    with pytest.raises(HTTPException) as error:
        fresh_guard().check_and_reserve_tokens('u', 100)
    assert 'call allowance' in error.value.detail


def test_money_cap_counts_all_tokens_without_a_token_ceiling(ledger):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1_100_000)
    guard.record_llm_usage('u', 1_100_000, 0, reservation=receipt, cost_usd='0.165')
    assert guard._get_daily_record('u').estimated_tokens == 1_100_000
    with pytest.raises(HTTPException) as error:
        guard.check_and_reserve_tokens('u', 2_400_000)
    assert '$0.50 daily AI allowance' in error.value.detail
    assert f'${limiter.dollars(limiter.DAILY_BUDGET_NANOS - 165_000_000):.2f}' in error.value.detail
    assert 'not an OpenRouter' in error.value.detail


def test_actual_provider_cost_releases_money_hold_once(ledger):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 10000, max_output_tokens=4000)
    guard.record_llm_usage('u', 1000, 100, reservation=receipt, cost_usd='0.0002')
    guard.record_llm_usage('u', 1000, 100, reservation=receipt, cost_usd='0.0002')
    assert guard._get_daily_record('u').cost_nanos == 200_000


def test_missing_billing_data_keeps_conservative_money_hold(ledger):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 10000, max_output_tokens=4000)
    before = guard._get_daily_record('u').cost_nanos
    guard.record_llm_usage('u', 10, 1, reservation=receipt)
    assert guard._get_daily_record('u').cost_nanos == before


def test_all_models_share_daily_spending_allowance(ledger):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1_000_000)
    guard.record_llm_usage('u', 1_000_000, 0, reservation=receipt, cost_usd='0.15')
    with pytest.raises(HTTPException):
        fresh_guard().check_and_reserve_tokens('u', 500_000, model='google/gemini-3.8-flash')


def test_money_holds_prevent_parallel_overspending(ledger):
    def reserve(_):
        try:
            fresh_guard().check_and_reserve_tokens('u', 1_000_000)
            return True
        except HTTPException: return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 3


def test_fifty_cent_allowance_keeps_existing_usage(ledger):
    from decimal import Decimal
    from src.settings import OPENROUTER_DAILY_BUDGET_USD
    assert OPENROUTER_DAILY_BUDGET_USD == 0.50
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('existing', 1_000_000)
    guard.record_llm_usage('existing', 1_000_000, 0, reservation=receipt, cost_usd='0.20')
    restarted = fresh_guard()
    assert restarted._get_daily_record('existing').cost_nanos == 200_000_000
    assert Decimal(limiter.DAILY_BUDGET_NANOS) / 1_000_000_000 <= Decimal('0.50')
    restarted.check_and_reserve_tokens('existing', 1_000_000)
    with pytest.raises(HTTPException) as error:
        restarted.check_and_reserve_tokens('existing', 2_000_000)
    assert '$0.50 daily AI allowance' in error.value.detail


def test_invalid_or_negative_provider_cost_cannot_refund_hold(ledger):
    for bad in ('NaN', '-1', 'invalid'):
        guard = fresh_guard()
        receipt = guard.check_and_reserve_tokens(bad, 1000)
        guard.record_llm_usage(bad, 10, 1, reservation=receipt, cost_usd=bad)
        assert guard._get_daily_record(bad).cost_nanos == 150_000


def test_search_fee_is_reserved_and_settled_in_shared_daily_budget(ledger):
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('web-user', 1000, extra_cost_nanos=1_000_000)
    assert guard._get_daily_record('web-user').cost_nanos >= 1_000_000
    guard.record_llm_usage('web-user', 100, 50, reservation=receipt, cost_usd='0.0012')
    assert guard._get_daily_record('web-user').cost_nanos == 1_200_000
    guard.record_llm_usage('web-user', 100, 50, reservation=receipt, cost_usd='0.0012')
    assert guard._get_daily_record('web-user').cost_nanos == 1_200_000


def test_search_fee_cannot_start_when_daily_balance_is_too_small(ledger, monkeypatch):
    monkeypatch.setattr(limiter, 'DAILY_BUDGET_NANOS', 999_999)
    guard = fresh_guard()
    with pytest.raises(HTTPException) as exc:
        guard.check_and_reserve_tokens('web-user', 0, extra_cost_nanos=1_000_000)
    assert exc.value.status_code == 429
    assert guard._get_daily_record('web-user').cost_nanos == 0


def test_status_read_never_creates_or_rewrites_ledger(ledger):
    guard = fresh_guard()
    assert guard._get_daily_record('unseen').cost_nanos == 0
    assert ledger.list('ai_usage') == []
    receipt = guard.check_and_reserve_tokens('u', 1000)
    before = deepcopy(ledger.list('ai_usage'))
    guard._get_daily_record('u')
    assert ledger.list('ai_usage') == before


def test_accounting_preserves_migration_marker(ledger):
    day = limiter.budget_day().isoformat()
    ledger.put('ai_usage', day, {'migration_id': 'old-ledger', 'cost_nanos': 123}, uid='u')
    guard = fresh_guard()
    receipt = guard.check_and_reserve_tokens('u', 1000)
    guard.record_llm_usage('u', 10, 10, reservation=receipt, cost_usd='0.00001')
    assert ledger.get('ai_usage', day, uid='u')['migration_id'] == 'old-ledger'
    assert guard._get_daily_record('u').cost_nanos == 10123


def test_timing_is_logged_even_when_reservation_rejected(ledger, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger=limiter.__name__):
        with pytest.raises(HTTPException):
            fresh_guard().check_and_reserve_tokens('u', 100_000_000)
    assert 'AI budget timing operation=reserve backend=sqlite latency_ms=' in caplog.text
