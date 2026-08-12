"""
Tasks Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager
import sqlite3


class TasksRepositoryMixin:
    """Mixin for tasks table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_task(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        task_id = str(data.get("id") or uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (id, uid, title, description, status, due_date, context_place, trigger_place, trigger_category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, uid, data.get("title", ""), data.get("description", ""),
                    data.get("status", "pending"), data.get("due_date"), data.get("context_place", ""),
                    data.get("trigger_place", ""), data.get("trigger_category", ""), now, now,
                ),
            )
        return {"id": task_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_task(self, uid: str, task_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND uid = ?", (task_id, uid)).fetchone()
        return dict(row) if row else None

    def update_task(self, uid: str, task_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_task(uid, task_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        fields = {**existing, **data, "updated_at": now}
        with self._conn() as conn:
            conn.execute(
                """UPDATE tasks SET title=?, description=?, status=?, due_date=?, context_place=?,
                   trigger_place=?, trigger_category=?, updated_at=?
                   WHERE id=? AND uid=?""",
                (
                    fields["title"], fields["description"], fields["status"],
                    fields.get("due_date"), fields.get("context_place", ""),
                    fields.get("trigger_place", ""), fields.get("trigger_category", ""),
                    now, task_id, uid,
                ),
            )
        return fields

    def delete_task(self, uid: str, task_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE id = ? AND uid = ?", (task_id, uid))
        return cursor.rowcount > 0

    def list_tasks(self, uid: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE uid = ? ORDER BY created_at DESC LIMIT ?", (
                    uid, limit)
            ).fetchall()
        return [dict(r) for r in rows]
