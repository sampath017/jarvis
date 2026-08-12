"""
Places Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager
import sqlite3


class PlacesRepositoryMixin:
    """Mixin for places table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_place(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        place_id = data.get("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        tags = data.get("tags", [])
        if not isinstance(tags, str):
            tags = json.dumps(tags)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO places
                   (id, uid, google_place_id, name, user_label, category, latitude, longitude, notes, tags, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    place_id, uid, data.get("google_place_id"), data.get("name", ""),
                    data.get("user_label"), data.get("category", ""),
                    data.get("latitude", 0.0), data.get("longitude", 0.0),
                    data.get("notes", ""), tags, now, now,
                ),
            )
        return {"id": place_id, "uid": uid, **data, "created_at": now, "updated_at": now}

    def get_place(self, uid: str, place_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM places WHERE id = ? AND uid = ?", (place_id, uid)).fetchone()
        return dict(row) if row else None

    def update_place(self, uid: str, place_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_place(uid, place_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        fields = {**existing, **data, "updated_at": now}
        tags = fields.get("tags", [])
        if not isinstance(tags, str):
            tags = json.dumps(tags)
        with self._conn() as conn:
            conn.execute(
                """UPDATE places SET google_place_id=?, name=?, user_label=?, category=?,
                   latitude=?, longitude=?, notes=?, tags=?, updated_at=? WHERE id=? AND uid=?""",
                (
                    fields.get("google_place_id"), fields["name"], fields.get("user_label"),
                    fields.get("category", ""), fields.get("latitude", 0.0),
                    fields.get("longitude", 0.0), fields.get("notes", ""), tags, now, place_id, uid,
                ),
            )
        return fields

    def delete_place(self, uid: str, place_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM places WHERE id = ? AND uid = ?", (place_id, uid))
        return cursor.rowcount > 0

    def list_places(self, uid: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM places WHERE uid = ? ORDER BY created_at DESC LIMIT ?", (
                    uid, limit)
            ).fetchall()
        return [dict(r) for r in rows]
