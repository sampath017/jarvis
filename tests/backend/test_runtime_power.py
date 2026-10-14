from unittest.mock import Mock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from src.api.power_middleware import PowerMiddleware
from src.services.runtime_power import RuntimePower
from src.services.sqlite_store import SqlStore
from src.backend.command_execution import CommandExecution, CommandStopped


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(RuntimePower, '_instance', None)
    yield
    RuntimePower._instance = None


def test_off_gate_stops_work_before_handlers_but_health_is_reachable(monkeypatch):
    monkeypatch.setattr(RuntimePower, 'enabled', lambda *a, **k: False)
    app = FastAPI()
    app.add_middleware(PowerMiddleware)
    handler = Mock()
    @app.post('/work')
    def work():
        handler()
    @app.get('/health')
    def health():
        return {'status': 'ok'}
    client = TestClient(app)
    assert client.post('/work').status_code == 503
    assert client.post('/work').json()['power_off'] is True
    handler.assert_not_called()
    assert client.get('/health').status_code == 200


def test_explicit_sql_power_handle_preserves_state_across_reopen(monkeypatch, tmp_path):
    path = tmp_path / 'power.db'
    first = SqlStore(path)
    monkeypatch.setattr(RuntimePower, 'store', lambda _: first)
    assert RuntimePower().set(False)['enabled'] is False
    first.db.close()
    reopened = SqlStore(path)
    try:
        monkeypatch.setattr(RuntimePower, 'store', lambda _: reopened)
        RuntimePower._instance = None
        assert RuntimePower().enabled(fresh=True) is False
        assert RuntimePower().set(True)['enabled'] is True
    finally:
        reopened.db.close()


def test_command_and_paid_budget_stop_before_new_work(monkeypatch):
    monkeypatch.setattr(RuntimePower, 'enabled', lambda *a, **k: False)
    with pytest.raises(CommandStopped, match='powered off'):
        CommandExecution(publish=Mock()).model_turn()
    from src.api.rate_limiter import TokenBudgetGuard
    with pytest.raises(HTTPException, match='powered off'):
        TokenBudgetGuard().check_and_reserve_tokens('user', 100)


def test_sql_gate_failure_fails_closed(monkeypatch):
    def fail(_):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(RuntimePower, 'status', fail)
    assert RuntimePower().enabled(fresh=True) is False
