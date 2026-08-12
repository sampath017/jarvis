"""
Mobility Sessions Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class SessionsRepositoryMixin:
    """Mixin for mobility_sessions table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def get_active_session(self, uid: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM mobility_sessions WHERE uid = ? AND status IN ('ACTIVE','PAUSED','RESUMED') LIMIT 1",
                (uid,),
            ).fetchone()
        return self._session_row_to_dict(row) if row else None

    def upsert_session(self, uid: str, session_id: str, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        parking_gps = data.get("parking_gps", {}) or {}
        events = data.get("events", [])
        if not isinstance(events, str):
            events = json.dumps(events)
        pois = data.get("poi_visits", [])
        if not isinstance(pois, str):
            pois = json.dumps(pois)

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO mobility_sessions
                   (id, uid, status, vehicle_class, started_at, last_updated, paused_at, completed_at,
                    parking_lat, parking_lon, parking_accuracy_m, classification_confidence,
                    resume_count, events_json, poi_visits_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, vehicle_class=excluded.vehicle_class,
                    last_updated=excluded.last_updated, paused_at=excluded.paused_at,
                    completed_at=excluded.completed_at, parking_lat=excluded.parking_lat,
                    parking_lon=excluded.parking_lon, parking_accuracy_m=excluded.parking_accuracy_m,
                    classification_confidence=excluded.classification_confidence,
                    resume_count=excluded.resume_count, events_json=excluded.events_json,
                    poi_visits_json=excluded.poi_visits_json, updated_at=excluded.updated_at""",
                (
                    session_id, uid, data.get("status", "CREATED"), data.get("vehicle_class", "UNKNOWN"),
                    data.get("started_at", now), data.get("last_updated", now),
                    data.get("paused_at"), data.get("completed_at"),
                    parking_gps.get("latitude"), parking_gps.get("longitude"), parking_gps.get("accuracy_m"),
                    data.get("classification_confidence", 0.0), data.get("resume_count", 0),
                    events, pois, now, now,
                ),
            )
        return {"id": session_id, "session_id": session_id, "uid": uid, **data}

    def _session_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["session_id"] = d["id"]
        d["events"] = json.loads(d.pop("events_json", "[]"))
        d["poi_visits"] = json.loads(d.pop("poi_visits_json", "[]"))
        if d.get("parking_lat") is not None:
            d["parking_gps"] = {
                "latitude": d.pop("parking_lat"),
                "longitude": d.pop("parking_lon"),
                "accuracy_m": d.pop("parking_accuracy_m", 10.0),
            }
        else:
            d.pop("parking_lat", None)
            d.pop("parking_lon", None)
            d.pop("parking_accuracy_m", None)
            d["parking_gps"] = None
        return d
