import hashlib
from unittest.mock import Mock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from src.api.power_middleware import PowerMiddleware
from src.api.routers.runtime_power import router
from src.services.runtime_power import RuntimePower
from src.backend.command_execution import CommandExecution, CommandStopped


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    RuntimePower._instance = None
    monkeypatch.delenv('K_SERVICE', raising=False)
    monkeypatch.delenv('JARVIS_POWER_CLOUD', raising=False)
    yield
    RuntimePower._instance = None


def test_off_rejects_application_and_tasks_before_handlers_but_control_is_reachable(monkeypatch):
    monkeypatch.setattr(RuntimePower, 'enabled', lambda *a, **k: False)
    monkeypatch.setenv('JARVIS_GOOGLE_OWNER_HASH', hashlib.sha256(('a'*64).encode()).hexdigest())
    monkeypatch.setattr(RuntimePower, 'status', lambda _: {'enabled': False, 'cloud_ready': True})
    app = FastAPI()
    app.add_middleware(PowerMiddleware)
    app.include_router(router)
    handler = Mock()
    @app.post('/internal/background/google-action')
    def action():
        handler()
    @app.get('/sync/pull')
    def sync():
        handler()
    client = TestClient(app)
    assert client.post('/internal/background/google-action').status_code == 503
    assert client.get('/sync/pull').json()['power_off'] is True
    handler.assert_not_called()
    assert client.get('/runtime/power').status_code == 403
    assert client.get('/runtime/power', headers={'X-Calendar-Session': 'b'*64}).status_code == 403
    assert client.get('/runtime/power', headers={'X-Calendar-Session': 'a'*64}).json()['enabled'] is False


def test_local_power_persists_across_instances_without_cloud_resources(monkeypatch, tmp_path):
    monkeypatch.setenv('JARVIS_LOCAL_DB_PATH', str(tmp_path / 'power.db'))
    assert RuntimePower().set(False)['enabled'] is False
    RuntimePower._instance = None
    assert RuntimePower().enabled(fresh=True) is False
    assert RuntimePower().set(True)['enabled'] is True
    RuntimePower._instance = None
    assert RuntimePower().enabled(fresh=True) is True


def test_command_and_paid_budget_stop_before_new_work(monkeypatch):
    monkeypatch.setattr(RuntimePower, 'enabled', lambda *a, **k: False)
    with pytest.raises(CommandStopped, match='powered off'):
        CommandExecution(publish=Mock()).model_turn()
    from src.api.rate_limiter import TokenBudgetGuard
    with pytest.raises(HTTPException, match='powered off'):
        TokenBudgetGuard().check_and_reserve_tokens('user', 100)


def test_cloud_storage_failure_fails_closed(monkeypatch):
    monkeypatch.setenv('JARVIS_POWER_CLOUD', '1')
    def fail(_): raise RuntimeError('unavailable')
    monkeypatch.setattr(RuntimePower, 'status', fail)
    assert RuntimePower().enabled(fresh=True) is False
