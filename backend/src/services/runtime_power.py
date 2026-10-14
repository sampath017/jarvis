"""Local API power gate. Android independently owns its phone power switch."""
import threading
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from src.services import sqlite_documents as documents


class RuntimePower:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._enabled = True
            cls._instance._checked = 0.0
            cls._instance._lock = threading.RLock()
        return cls._instance

    def reference(self):
        db = documents.Client()
        return db.collection('runtime_control').document('jarvis')

    def status(self):
        from .mobile_scope import mobile_only
        if mobile_only():
            return {'enabled': True, 'cloud_ready': True}
        value = self.reference().get().to_dict() or {'enabled': True, 'cloud_ready': True}
        with self._lock:
            self._enabled = value.get('enabled', True) is True
            self._checked = time.monotonic()
        return {key: value[key] for key in ('enabled', 'cloud_ready', 'updated_at', 'errors', 'transition') if key in value}

    def enabled(self, *, fresh=False):
        # HTTP requests read the durable state; active command steps cache briefly.
        # An idle Off instance performs no recurring reads and no reminder sweep.
        if fresh or time.monotonic() - self._checked > 2:
            try:
                return self.status()['enabled']
            except Exception:
                self._enabled = False  # Fail closed: no paid work without a gate.
                return False
        return self._enabled

    @property
    def locally_enabled(self):
        return self._enabled

    def require_enabled(self):
        if not self.enabled():
            raise HTTPException(503, 'Jarvis is powered off. Turn it on in Settings.')

    def set(self, enabled):
        with self._lock:
            result = {'enabled': bool(enabled), 'cloud_ready': True,
                      'updated_at': datetime.now(timezone.utc), 'errors': []}
            self.reference().set(result)
            self._enabled = bool(enabled)
            self._checked = time.monotonic()
        return result
