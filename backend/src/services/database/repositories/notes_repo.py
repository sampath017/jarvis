"""
Notes Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager
import sqlite3


class NotesRepositoryMixin:
    """Mixin for notes table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_note(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        note_id = data.get("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        tags = data.get("tags", [])
        if not isinstance(tags, str):
            tags = json.dumps(tags)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO notes
                   (id, uid, title, content, place, category, tags, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    note_id, uid, data.get("title", ""), data.get("content", ""),
                    data.get("place", ""), data.get("category", ""), tags, now, now,
                ),
            )
        return {"id": note_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_note(self, uid: str, note_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM notes WHERE id = ? AND uid = ?", (note_id, uid)).fetchone()
        return dict(row) if row else None

    def update_note(self, uid: str, note_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_note(uid, note_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        fields = {**existing, **data, "updated_at": now}
        with self._conn() as conn:
            conn.execute(
                "UPDATE notes SET title=?, content=?, updated_at=? WHERE id=? AND uid=?",
                (fields["title"], fields["content"], now, note_id, uid),
            )
        return fields

    def delete_note(self, uid: str, note_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM notes WHERE id = ? AND uid = ?", (note_id, uid))
        return cursor.rowcount > 0

    def list_notes(self, uid: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM notes WHERE uid = ? ORDER BY created_at DESC LIMIT ?", (
                    uid, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def find_note_by_title(self, uid: str, title_match: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM notes WHERE uid = ? AND lower(title) LIKE lower(?)
                   ORDER BY updated_at DESC LIMIT 1""",
                (uid, f"%{title_match}%"),
            ).fetchone()
        return dict(row) if row else None
