import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from src.api.routers import session_library as library


class Store:
    def __init__(self):
        self.rows = {}

    def document(self, key):
        store = self
        class Document:
            def set(self, value):
                store.rows[key] = value
        return Document()

    def stream(self):
        class Snapshot:
            def __init__(self, value):
                self.value = value
            def to_dict(self):
                return self.value
        return [Snapshot(v) for v in self.rows.values()]


def test_preferences_survive_new_client_and_restore(monkeypatch):
    stores = {}
    monkeypatch.setattr(library, 'collection', lambda uid, kind: stores.setdefault((uid, kind), Store()))
    value = library.Preference(id='journey:abc', name='Evening walk', archived=True)
    library.save_preference(value, 'user-a')
    assert library.preferences('user-a')['items'] == [value.model_dump()]
    assert library.preferences('user-b')['items'] == []
    library.save_preference(value.model_copy(update={'archived': False}), 'user-a')
    assert library.preferences('user-a')['items'][0]['archived'] is False


def test_names_are_bounded_and_keys_cannot_escape_paths():
    with pytest.raises(ValidationError):
        library.Preference(id='a', name='x' * 61)
    assert '/' not in library.key('../../other-user')
    assert library.key('a') != library.key('b')


def test_incomplete_backup_is_not_published(monkeypatch):
    class Blob:
        size = 2
        def reload(self):
            pass
        def exists(self):
            return False
    monkeypatch.setattr(library, 'blob', lambda *args: Blob())
    value = library.Recording(id='r1', start_time='2026-10-03T09:00:00Z', label='Walk', sample_count=1, duration_seconds=1, csv_size_bytes=2)
    with pytest.raises(HTTPException) as error:
        library.save_recording(value, 'user-a')
    assert error.value.status_code == 409


def test_storage_unavailable_is_not_success(monkeypatch):
    class Offline:
        is_available = False
    monkeypatch.setattr(library, 'FirestoreService', Offline)
    with pytest.raises(HTTPException) as error:
        library.preferences('user-a')
    assert error.value.status_code == 503
