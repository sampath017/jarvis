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
            existing = conn.execute(
                "SELECT uid, created_at, boundary_json FROM places WHERE id = ?", (place_id,)
            ).fetchone()
            if existing is not None and existing["uid"] != uid:
                raise ValueError("Record belongs to another user")
            created_at = data.get("created_at") or (existing["created_at"] if existing else now)
            updated_at = data.get("updated_at") or now
            boundary = data.get('boundary_json', existing['boundary_json'] if existing else None)
            if isinstance(boundary, dict):
                boundary = json.dumps(boundary)
            cursor = conn.execute(
                """INSERT INTO places
                   (id, uid, google_place_id, name, user_label, category, latitude, longitude, notes, tags, created_at, updated_at, boundary_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       google_place_id=excluded.google_place_id, name=excluded.name,
                       user_label=excluded.user_label, category=excluded.category,
                       latitude=excluded.latitude, longitude=excluded.longitude,
                       notes=excluded.notes, tags=excluded.tags,
                       created_at=excluded.created_at, updated_at=excluded.updated_at,
                       boundary_json=excluded.boundary_json
                   WHERE places.uid=excluded.uid""",
                (
                    place_id, uid, data.get("google_place_id"), data.get("name", ""),
                    data.get("user_label"), data.get("category", ""),
                    data.get("latitude", 0.0), data.get("longitude", 0.0),
                    data.get("notes", ""), tags, created_at, updated_at, boundary,
                ),
            )
            # The conflict guard also covers an owner inserting the key between
            # the read and write when using separate explicit SQL connections.
            if cursor.rowcount == 0:
                raise ValueError("Record belongs to another user")
        return {**data, "id": place_id, "uid": uid, "created_at": created_at, "updated_at": updated_at}

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
                   latitude=?, longitude=?, notes=?, tags=?, updated_at=?, boundary_json=? WHERE id=? AND uid=?""",
                (
                    fields.get("google_place_id"), fields["name"], fields.get("user_label"),
                    fields.get("category", ""), fields.get("latitude", 0.0),
                    fields.get("longitude", 0.0), fields.get("notes", ""), tags, now,
                    json.dumps(fields['boundary_json']) if isinstance(fields.get('boundary_json'),dict) else fields.get('boundary_json'), place_id, uid,
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
