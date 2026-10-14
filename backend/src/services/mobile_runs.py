"""Active request coordination in RAM; no restart recovery or disk receipts."""
import threading
import time
from .mobile_scope import MobileScope, current

_lock = threading.RLock()
_database = None
_scopes = {}
_finished = {}


def database():
    global _database
    from .sqlite_documents import Client
    with _lock:
        if _database is None:
            scope = MobileScope()
            token = current.set(scope)
            try:
                _database = Client()
            finally:
                current.reset(token)
        for key, at in list(_finished.items()):
            if time.monotonic() - at >= 60:
                uid, request_id = key
                import hashlib
                _database.collection('users').document(uid).collection('command_runs').document(
                    hashlib.sha256(request_id.encode()).hexdigest()).delete()
                del _finished[key]
        return _database


def accept(uid, request_id):
    scope = current.get()
    with _lock:
        scope.retain()
        _scopes[uid, request_id] = scope


def changes(uid, request_id):
    with _lock:
        scope = _scopes.get((uid, request_id))
        return scope.changes() if scope else None


def finish(uid, request_id):
    with _lock:
        scope = _scopes.pop((uid, request_id), None)
        if scope:
            scope.release()
        _finished[uid, request_id] = time.monotonic()
        def forget():
            with _lock:
                import hashlib
                _database.collection('users').document(uid).collection('command_runs').document(
                    hashlib.sha256(request_id.encode()).hexdigest()).delete()
                _finished.pop((uid, request_id), None)
        timer = threading.Timer(60, forget)
        timer.daemon = True
        timer.start()
