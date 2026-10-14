"""Pytest plugin: reject external sockets while exercising real local SQLite."""
from __future__ import annotations

import ipaddress
import socket
import pytest

_originals = {}


def _local(address):
    if not isinstance(address, tuple):  # Unix-domain sockets do not use the network.
        return True
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def pytest_sessionstart(session):
    from src.services.record_store import RecordStore

    _originals["record_store_instance"] = RecordStore._instance
    _originals["connect"] = socket.socket.connect
    _originals["connect_ex"] = socket.socket.connect_ex

    def connect(self, address):
        if not _local(address):
            raise RuntimeError("Offline harness blocked an external network connection")
        return _originals["connect"](self, address)

    def connect_ex(self, address):
        if not _local(address):
            raise RuntimeError("Offline harness blocked an external network connection")
        return _originals["connect_ex"](self, address)

    RecordStore._instance = None
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def pytest_sessionfinish(session, exitstatus):
    from src.services.record_store import RecordStore

    RecordStore._instance = _originals["record_store_instance"]
    socket.socket.connect = _originals["connect"]
    socket.socket.connect_ex = _originals["connect_ex"]


@pytest.fixture(autouse=True)
def isolated_sql_records(monkeypatch):
    """Exercise the production SQL repositories with an explicit test-only handle."""
    from src.services.record_store import RecordStore
    from src.services.sqlite_store import SqlStore
    from src.services.runtime_power import RuntimePower
    store = SqlStore(':memory:')
    monkeypatch.setattr(RecordStore, '_instance', RecordStore.from_sql(store))
    monkeypatch.setattr(RuntimePower, '_instance', None)
    yield store
    store.db.close()
