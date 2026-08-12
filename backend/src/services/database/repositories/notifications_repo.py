"""
Notifications Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class NotificationsRepositoryMixin:
    """Mixin for notifications table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_notification(self, uid: str, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        notification_id = data.get("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        payload = data.get("payload", {})
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO notifications
                   (id, uid, reminder_id, context_rule_id, title, body, trigger_type,
                    event_id, status, payload_json, delivered_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    notification_id, uid, data.get("reminder_id"), data.get("context_rule_id"),
                    data["title"], data.get("body", ""), data["trigger_type"],
                    data.get("event_id", ""), data.get("status", "PENDING"),
                    json.dumps(payload), data.get("delivered_at"), now,
                ),
            )
            created = cursor.rowcount > 0
            if created:
                row = conn.execute(
                    "SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM notifications WHERE uid = ? AND reminder_id IS ?
                       AND context_rule_id IS ? AND event_id = ?""",
                    (uid, data.get("reminder_id"), data.get("context_rule_id"), data.get("event_id", "")),
                ).fetchone()
        return self._notification_row_to_dict(row), created

    def list_notifications(self, uid: str, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM notifications WHERE uid = ?"
        params: list[Any] = [uid]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._notification_row_to_dict(row) for row in rows]

    def acknowledge_notification(self, uid: str, notification_id: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE notifications SET status = 'DELIVERED', delivered_at = ?
                   WHERE id = ? AND uid = ?""",
                (now, notification_id, uid),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        return self._notification_row_to_dict(row)

    @staticmethod
    def _notification_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json", "{}"))
        return result
