"""Read-only context evidence and geometry shared by rules and agent tools."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _coordinate(value: Any, limit: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and -limit <= number <= limit else None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres, including antipodal rounding guards."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi, delta_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    value = min(1.0, max(0.0, value))
    return 6_371_000.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def geofence_result(location: dict[str, Any], target: dict[str, Any], *, default_radius_m: float = 150.0) -> dict[str, Any]:
    """Evaluate the same point-in-radius condition used by reminder rules."""
    coordinates = (_coordinate(location.get("latitude"), 90), _coordinate(location.get("longitude"), 180),
                   _coordinate(target.get("latitude"), 90), _coordinate(target.get("longitude"), 180))
    try:
        radius = float(target.get("radius_m", default_radius_m))
    except (TypeError, ValueError):
        radius = -1
    if None in coordinates or not math.isfinite(radius) or radius < 0:
        return {"status": "uncertain", "inside": False, "distance_m": None, "reason": "Missing or invalid coordinates/radius."}
    distance = haversine_m(*coordinates)
    return {"status": "ok", "inside": distance <= radius, "distance_m": distance, "radius_m": radius,
            "accuracy_m": location.get("accuracy_m"), "source": "point_in_radius"}


def vibration_evidence(features: dict[str, Any] | None) -> dict[str, Any]:
    """Inspect a spectral hint; a hint alone cannot verify a particular vehicle.

    Android's bounded-burst classifier remains the source of verified vehicle
    labels. Real, positive measurements are required before offering a candidate.
    """
    features = features or {}
    frequency = features.get("dominant_frequency_hz", features.get("dominant_freq_hz"))
    rms = features.get("rms_energy", features.get("z_rms"))
    try:
        frequency, rms = float(frequency), float(rms)
    except (TypeError, ValueError):
        frequency = rms = 0.0
    result = {"status": "uncertain", "candidate": "UNKNOWN", "confidence": 0.0, "verified": False,
              "dominant_frequency_hz": frequency, "rms_energy": rms, "source": "spectral_baseline"}
    if not math.isfinite(frequency) or not math.isfinite(rms) or frequency <= 0 or rms <= 0:
        return {**result, "dominant_frequency_hz": frequency if math.isfinite(frequency) else None,
                "rms_energy": rms if math.isfinite(rms) else None,
                "reason": "INCONCLUSIVE: Missing, zero or invalid vibration measurements."}
    if 20 <= frequency <= 45 and rms >= 0.5:
        return {**result, "status": "candidate", "candidate": "HUNTER_350",
                "confidence": 0.92 if 25 <= frequency <= 38 else 0.78,
                "reason": "Royal Enfield Hunter 350 baseline is compatible; this does not identify or confirm the vehicle."}
    if frequency <= 4:
        return {**result, "status": "candidate", "candidate": "NOT_VEHICLE", "confidence": 0.9,
                "reason": "Pedestrian movement baseline (Walking / Running); requires activity evidence."}
    if frequency < 15 and rms < 0.5:
        return {**result, "status": "candidate", "candidate": "CAR", "confidence": 0.85,
                "reason": "Enclosed vehicle (Car / Bus) baseline is compatible; requires classifier evidence."}
    return {**result, "reason": "INCONCLUSIVE: Measurements do not distinctly match a spectral baseline."}


class ContextEvidenceService:
    """A scoped view of the current event or the user's last saved observation."""

    def __init__(self, db, uid: str, *, state: dict[str, Any] | None = None) -> None:
        self.db, self.uid, self.state = db, uid, state or {}

    def observation(self) -> dict[str, Any]:
        packet = self.state.get("context_packet") or {}
        if self.state.get("request_type") == "CONTEXT_EVENT":
            return {**(self.state.get("raw_request") or {}), **packet}
        return self.db.get_latest_context_event(self.uid) or {}

    def current_context(self, *, now: datetime | None = None) -> dict[str, Any]:
        observation = self.observation()
        observed_at = observation.get("timestamp") or observation.get("occurred_at")
        age = None
        if observed_at:
            try:
                observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
                if observed.tzinfo is not None:
                    age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
            except (TypeError, ValueError):
                pass
        fresh = age is not None and 0 <= age <= 300
        return {"status": "ok" if observation else "unavailable", "fresh": fresh, "age_seconds": age,
                "observed_at": observed_at, "activity": observation.get("activity", "UNKNOWN"),
                "activity_evidence": observation.get("activity_evidence"),
                "gps": observation.get("gps") or observation.get("location"),
                "event_id": observation.get("event_id") or observation.get("id"),
                "conflicts": self.state.get("conflicts", []),
                "source": "current_event" if self.state.get("request_type") == "CONTEXT_EVENT" else "saved_observation",
                "note": "Historical or stale observations do not prove current activity or presence."}

    def motion_evidence(self) -> dict[str, Any]:
        observation = self.observation()
        features = observation.get("feature_summary") or observation.get("imu") or {}
        if not isinstance(features, dict):
            features = {}
        return {"event_id": observation.get("event_id") or observation.get("id"),
                "observed_at": observation.get("timestamp") or observation.get("occurred_at"),
                "activity": observation.get("activity", "UNKNOWN"), "features": features,
                "vehicle_class_hint": observation.get("vehicle_class_hint") or features.get("vehicle_class_hint") or "UNKNOWN",
                "classification_confidence": observation.get("classification_confidence", features.get("classification_confidence", 0)),
                "spectral_hint": vibration_evidence(features)}

    def saved_geofences(self, latitude: float | None, longitude: float | None) -> list[dict[str, Any]]:
        location = {"latitude": latitude, "longitude": longitude}
        return [{"place_id": place.get("id"), "name": place.get("name"), "category": place.get("category"),
                 **geofence_result(location, place)} for place in self.db.list_places(self.uid)]

    def monitoring_status(self) -> dict[str, Any]:
        observation = self.observation()
        return {"owner": "Android", "enabled": None, "permissions": "unknown",
                "location_status": observation.get("location_status"),
                "last_observed_at": observation.get("timestamp") or observation.get("occurred_at"),
                "note": "Backend observations cannot confirm current Android monitoring settings or grant permissions. Check phone Settings."}
