"""
Reminders Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class RemindersRepositoryMixin:
    """Mixin for reminders table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_reminder(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        reminder_id = data.get("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO reminders
                   (id, uid, title, body, due_at, location_name, latitude, longitude,
                    radius_m, activity, status, one_shot, last_fired_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    reminder_id, uid, data["title"], data.get("body", ""),
                    data.get("due_at"), data.get("location_name"), data.get("latitude"),
                    data.get("longitude"), data.get("radius_m", 100.0),
                    data.get("activity"), data.get("status", "ACTIVE"),
                    int(data.get("one_shot", True)), data.get("last_fired_at"), now, now,
                ),
            )
        return {"id": reminder_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_reminder(self, uid: str, reminder_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ? AND uid = ?", (reminder_id, uid)
            ).fetchone()
        return self._reminder_row_to_dict(row) if row else None

    def update_reminder(self, uid: str, reminder_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_reminder(uid, reminder_id)
        if not existing:
            return None
        fields = {**existing, **data}
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE reminders SET title=?, body=?, due_at=?, location_name=?, latitude=?,
                   longitude=?, radius_m=?, activity=?, status=?, one_shot=?, last_fired_at=?,
                   updated_at=? WHERE id=? AND uid=?""",
                (
                    fields["title"], fields.get("body", ""), fields.get("due_at"),
                    fields.get("location_name"), fields.get("latitude"), fields.get("longitude"),
                    fields.get("radius_m", 100.0), fields.get("activity"),
                    fields.get("status", "ACTIVE"), int(fields.get("one_shot", True)),
                    fields.get("last_fired_at"), now, reminder_id, uid,
                ),
            )
        return {**fields, "id": reminder_id, "uid": uid, "updated_at": now}

    def complete_reminder(self, uid: str, reminder_id: str) -> dict[str, Any] | None:
        return self.update_reminder(uid, reminder_id, {"status": "COMPLETED"})

    def delete_reminder(self, uid: str, reminder_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE id = ? AND uid = ?", (reminder_id, uid))
        return cursor.rowcount > 0

    def list_reminders(
        self, uid: str, status: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM reminders WHERE uid = ?"
        params: list[Any] = [uid]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._reminder_row_to_dict(row) for row in rows]

    def find_reminder_by_title(self, uid: str, title_match: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM reminders WHERE uid = ? AND lower(title) LIKE lower(?)
                   ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, updated_at DESC LIMIT 1""",
                (uid, f"%{title_match}%"),
            ).fetchone()
        return self._reminder_row_to_dict(row) if row else None

    def list_due_reminders(self, now: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM reminders
                   WHERE status = 'ACTIVE' AND due_at IS NOT NULL AND due_at <= ?
                     AND last_fired_at IS NULL""",
                (now,),
            ).fetchall()
        return [self._reminder_row_to_dict(row) for row in rows]

    @staticmethod
    def _reminder_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["one_shot"] = bool(result.get("one_shot"))
        return result
