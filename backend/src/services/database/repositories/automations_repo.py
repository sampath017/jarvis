"""
Automations Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager
import sqlite3


class AutomationsRepositoryMixin:
    """Mixin for automations table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_automation(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        auto_id = data.get("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        config = data.get("config", {})
        if not isinstance(config, str):
            config = json.dumps(config)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO automations
                   (id, uid, name, trigger_type, action_type, config_json, enabled, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    auto_id, uid, data.get("name", ""), data.get("trigger_type", ""),
                    data.get("action_type", ""), config, int(data.get("enabled", True)), now, now,
                ),
            )
        return {"id": auto_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_automation(self, uid: str, auto_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM automations WHERE id = ? AND uid = ?", (auto_id, uid)).fetchone()
        return dict(row) if row else None

    def update_automation(self, uid: str, auto_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_automation(uid, auto_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        fields = {**existing, **data, "updated_at": now}
        config = fields.get("config", fields.get("config_json", "{}"))
        if not isinstance(config, str):
            config = json.dumps(config)
        with self._conn() as conn:
            conn.execute(
                """UPDATE automations SET name=?, trigger_type=?, action_type=?, config_json=?, enabled=?, updated_at=?
                   WHERE id=? AND uid=?""",
                (
                    fields.get("name", ""), fields.get("trigger_type", ""), fields.get("action_type", ""),
                    config, int(fields.get("enabled", True)), now, auto_id, uid,
                ),
            )
        return fields

    def delete_automation(self, uid: str, auto_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM automations WHERE id = ? AND uid = ?", (auto_id, uid))
        return cursor.rowcount > 0

    def list_automations(self, uid: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM automations WHERE uid = ? ORDER BY created_at DESC LIMIT ?", (
                    uid, limit)
            ).fetchall()
        return [dict(r) for r in rows]
