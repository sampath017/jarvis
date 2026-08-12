"""
Context Events Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class EventsRepositoryMixin:
    """Mixin for context_events table operations."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def create_event_idempotent(self, uid: str, event_id: str, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM context_events WHERE id = ?", (event_id,)).fetchone()
            if existing:
                row = conn.execute(
                    "SELECT * FROM context_events WHERE id = ?", (event_id,)).fetchone()
                return self._event_row_to_dict(row), False

        now = datetime.now(timezone.utc).isoformat()
        gps = data.get("gps", {}) or {}
        fs = data.get("feature_summary")
        if fs and not isinstance(fs, str):
            fs = json.dumps(fs)
        pois = data.get("nearby_pois", [])
        if not isinstance(pois, str):
            pois = json.dumps(pois)

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO context_events
                   (id, uid, activity, transition, gps_lat, gps_lon, gps_accuracy_m, gps_speed_mps, gps_bearing_deg,
                    feature_summary_json, session_id, classification_confidence, vehicle_class_hint,
                    nearby_pois_json, timestamp, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, uid, data.get("activity", ""), data.get("transition", "ENTER"),
                    gps.get("latitude"), gps.get("longitude"), gps.get("accuracy_m"),
                    gps.get("speed_mps"), gps.get("bearing_deg"),
                    fs, data.get("session_id"), data.get("classification_confidence", 0.0),
                    data.get("vehicle_class_hint", ""), pois,
                    data.get("timestamp", now), now,
                ),
            )
        record = {"id": event_id, "uid": uid, **data, "created_at": now}
        return record, True

    def get_latest_gps(self, uid: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT gps_lat, gps_lon, gps_accuracy_m, gps_speed_mps, gps_bearing_deg
                   FROM context_events WHERE uid = ? AND gps_lat IS NOT NULL
                   ORDER BY timestamp DESC LIMIT 1""",
                (uid,),
            ).fetchone()
        if not row:
            return None
        return {
            "latitude": row["gps_lat"],
            "longitude": row["gps_lon"],
            "accuracy_m": row["gps_accuracy_m"],
            "speed_mps": row["gps_speed_mps"],
            "bearing_deg": row["gps_bearing_deg"],
        }

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if d.get("gps_lat") is not None:
            d["gps"] = {
                "latitude": d.pop("gps_lat"),
                "longitude": d.pop("gps_lon"),
                "accuracy_m": d.pop("gps_accuracy_m"),
                "speed_mps": d.pop("gps_speed_mps"),
                "bearing_deg": d.pop("gps_bearing_deg"),
            }
        else:
            for k in ("gps_lat", "gps_lon", "gps_accuracy_m", "gps_speed_mps", "gps_bearing_deg"):
                d.pop(k, None)
            d["gps"] = None
        d["feature_summary"] = json.loads(d.pop("feature_summary_json")) if d.get(
            "feature_summary_json") else None
        d["nearby_pois"] = json.loads(d.pop("nearby_pois_json", "[]"))
        return d
