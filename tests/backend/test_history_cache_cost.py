from datetime import datetime, timezone
from unittest.mock import Mock

from src.services.activity_history_cache import ActivityHistoryCache
from src.services.record_store import RecordStore


def test_history_reused_only_for_same_owner_window_and_revision():
    cache = ActivityHistoryCache()
    revision = [1]
    compute = Mock(return_value={'observations': [{'event_id': 'a'}], 'truncated': False})
    first = cache.get_or_compute(('alice', 'day'), lambda: revision[0], compute)
    first['observations'].clear()
    assert cache.get_or_compute(('alice', 'day'), lambda: revision[0], compute)['observations']
    assert compute.call_count == 1
    revision[0] += 1
    cache.get_or_compute(('alice', 'day'), lambda: revision[0], compute)
    cache.get_or_compute(('bob', 'day'), lambda: revision[0], compute)
    assert compute.call_count == 3


def test_incomplete_and_concurrently_changed_history_never_cached():
    cache = ActivityHistoryCache()
    compute = Mock(return_value={'truncated': True})
    for _ in range(2):
        cache.get_or_compute('day', lambda: 1, compute)
    assert compute.call_count == 2
    revision = [1]
    def changed():
        revision[0] += 1
        return {'observations': [], 'truncated': False}
    cache.get_or_compute('other', lambda: revision[0], changed)
    assert 'other' not in cache.entries


def test_cache_enforces_size_and_expiry():
    cache = ActivityHistoryCache(max_entries=1, max_bytes=100, ttl=0)
    compute = Mock(return_value={'data': 'small'})
    cache.get_or_compute('a', lambda: 1, compute)
    cache.get_or_compute('a', lambda: 1, compute)
    assert compute.call_count == 2
    cache.get_or_compute('b', lambda: 1, compute)
    assert list(cache.entries) == ['b']
    cache.get_or_compute('large', lambda: 1, lambda: {'data': 'x' * 1000})
    assert 'large' not in cache.entries


def test_version_checks_requested_local_days_and_mobility():
    fs = object.__new__(RecordStore)
    ref = Mock()
    ref.get.return_value.to_dict.return_value = {'mobility': 2, 'days': {'2026-10-14': 3, '2026-10-15': 4}}
    fs._user_collection = Mock(return_value=Mock(document=Mock(return_value=ref)))
    start = datetime(2026, 10, 13, 18, 30, tzinfo=timezone.utc)
    end = datetime(2026, 10, 14, 18, 30, tzinfo=timezone.utc)
    assert fs.history_revision('alice', start, end) == (2, (('2026-10-12', 0), ('2026-10-13', 0), ('2026-10-14', 3)))
    ref.get.assert_called_once()
