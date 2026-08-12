"""
Context Rules & Trigger State Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class ContextRulesRepositoryMixin:
    """Mixin for context_rules and context_trigger_state tables."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_context_rule(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        rule_id = data.get("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        trigger = data.get("trigger", {})
        action = data.get("action", {})
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO context_rules
                   (id, uid, name, trigger_type, trigger_json, action_type, action_json,
                    enabled, one_shot, last_fired_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rule_id, uid, data["name"], data["trigger_type"], json.dumps(trigger),
                    data["action_type"], json.dumps(action), int(data.get("enabled", True)),
                    int(data.get("one_shot", False)), data.get("last_fired_at"), now, now,
                ),
            )
        return {"id": rule_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_context_rule(self, uid: str, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM context_rules WHERE id = ? AND uid = ?", (rule_id, uid)
            ).fetchone()
        return self._context_rule_row_to_dict(row) if row else None

    def update_context_rule(self, uid: str, rule_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_context_rule(uid, rule_id)
        if not existing:
            return None
        fields = {**existing, **data}
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE context_rules SET name=?, trigger_type=?, trigger_json=?, action_type=?,
                   action_json=?, enabled=?, one_shot=?, last_fired_at=?, updated_at=?
                   WHERE id=? AND uid=?""",
                (
                    fields["name"], fields["trigger_type"], json.dumps(fields.get("trigger", {})),
                    fields["action_type"], json.dumps(fields.get("action", {})),
                    int(fields.get("enabled", True)), int(fields.get("one_shot", False)),
                    fields.get("last_fired_at"), now, rule_id, uid,
                ),
            )
        return {**fields, "id": rule_id, "uid": uid, "updated_at": now}

    def delete_context_rule(self, uid: str, rule_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM context_rules WHERE id = ? AND uid = ?", (rule_id, uid))
        return cursor.rowcount > 0

    def list_context_rules(self, uid: str, enabled: bool | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM context_rules WHERE uid = ?"
        params: list[Any] = [uid]
        if enabled is not None:
            query += " AND enabled = ?"
            params.append(int(enabled))
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._context_rule_row_to_dict(row) for row in rows]

    @staticmethod
    def _context_rule_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["trigger"] = json.loads(result.pop("trigger_json", "{}"))
        result["action"] = json.loads(result.pop("action_json", "{}"))
        result["enabled"] = bool(result.get("enabled"))
        result["one_shot"] = bool(result.get("one_shot"))
        return result

    def get_trigger_state(self, uid: str, source_type: str, source_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM context_trigger_state
                   WHERE uid = ? AND source_type = ? AND source_id = ?""",
                (uid, source_type, source_id),
            ).fetchone()
        return dict(row) if row else None

    def upsert_trigger_state(
        self, uid: str, source_type: str, source_id: str, is_inside: bool,
        event_id: str, seen_at: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO context_trigger_state
                   (uid, source_type, source_id, is_inside, last_event_id, last_seen_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(uid, source_type, source_id) DO UPDATE SET
                    is_inside=excluded.is_inside, last_event_id=excluded.last_event_id,
                    last_seen_at=excluded.last_seen_at""",
                (uid, source_type, source_id, int(is_inside), event_id, seen_at),
            )
