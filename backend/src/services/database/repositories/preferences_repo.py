"""
Preferences Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager
import sqlite3


class PreferencesRepositoryMixin:
    """Mixin for preferences table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_preference(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        pref_id = data.get("id", data.get("key", str(uuid.uuid4())))
        now = datetime.now(timezone.utc).isoformat()
        value = data.get("value")
        if not isinstance(value, str):
            value = json.dumps(value)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO preferences
                   (id, uid, key, value, source, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (pref_id, uid, data.get("key", pref_id), value, data.get("source", "user"), now, now),
            )
        return {"id": pref_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_preference(self, uid: str, pref_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM preferences WHERE (id = ? OR key = ?) AND uid = ?", (pref_id, pref_id, uid)
            ).fetchone()
        return dict(row) if row else None

    def update_preference(self, uid: str, pref_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_preference(uid, pref_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        value = data.get("value", existing.get("value"))
        if not isinstance(value, str):
            value = json.dumps(value)
        with self._conn() as conn:
            conn.execute(
                "UPDATE preferences SET key=?, value=?, source=?, updated_at=? WHERE (id=? OR key=?) AND uid=?",
                (
                    data.get("key", existing["key"]), value,
                    data.get("source", existing.get("source", "user")), now, pref_id, pref_id, uid,
                ),
            )
        return {**existing, **data, "value": value, "updated_at": now}

    def delete_preference(self, uid: str, pref_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM preferences WHERE (id = ? OR key = ?) AND uid = ?", (pref_id, pref_id, uid)
            )
        return cursor.rowcount > 0

    def list_preferences(self, uid: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM preferences WHERE uid = ? ORDER BY created_at DESC LIMIT ?", (uid, limit)
            ).fetchall()
        return [dict(r) for r in rows]
