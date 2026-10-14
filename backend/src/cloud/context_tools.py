"""Typed read-only tools over the same context services used by event rules."""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from ..services.context_evidence import ContextEvidenceService, geofence_result, vibration_evidence


BACKGROUND_CONTEXT_TOOL_NAMES = frozenset({
    "get_current_context", "get_motion_evidence", "check_geofence", "get_monitoring_status",
    "preview_reminder_match", "lookup_nearby_places", "match_vibration_signature",
    "check_saved_geofences", "check_user_geofences",
})


def build_context_tools(db, uid: str, *, state: dict[str, Any] | None = None) -> list[Any]:
    """Build capabilities for one invocation; no tool can write user records."""
    service = ContextEvidenceService(db, uid, state=state)

    @tool
    def get_current_context() -> dict:
        """Read current-event or last saved activity/location evidence with timestamps and freshness."""
        return service.current_context()

    @tool
    def get_motion_evidence() -> dict:
        """Read observed sensor features and classifier labels; spectral hints alone do not verify a vehicle."""
        return service.motion_evidence()

    @tool
    def get_monitoring_status() -> dict:
        """Report observed Android monitoring health. Unreported permissions and settings remain unknown."""
        return service.monitoring_status()

    @tool
    def check_geofence(latitude: float, longitude: float, target_latitude: float, target_longitude: float,
                       radius_m: float = 150.0) -> dict:
        """Calculate whether an explicit observation lies inside a radius using deterministic reminder geometry."""
        return geofence_result({"latitude": latitude, "longitude": longitude},
                               {"latitude": target_latitude, "longitude": target_longitude, "radius_m": radius_m})

    @tool
    def preview_reminder_match(reminder_id: str, event: dict | None = None) -> dict:
        """Explain an existing reminder match without updating trigger state, arming timers, or delivering alerts."""
        from ..backend.context_automation import ContextAutomationService
        evaluator = ContextAutomationService(db=db, cloud=False)
        reminder = db.get_reminder(uid, reminder_id)
        if not reminder:
            return {"status": "unavailable", "matches": False, "reason": "Reminder not found for this user."}
        return evaluator.preview_reminder_match(uid, reminder, event or service.observation())

    @tool
    def lookup_nearby_places(lat: float | None = None, lon: float | None = None,
                             latitude: float | None = None, longitude: float | None = None) -> str:
        """Look up nearby named places for explicit GPS coordinates; candidates do not prove presence."""
        effective_lat, effective_lon = latitude if latitude is not None else lat, longitude if longitude is not None else lon
        validation = geofence_result({"latitude": effective_lat, "longitude": effective_lon},
                                     {"latitude": effective_lat, "longitude": effective_lon})
        if validation["status"] != "ok":
            return "Places lookup unavailable: explicit valid coordinates are required."
        try:
            from ..services.places_client import PlacesClient
            pois = PlacesClient().search_nearby(latitude=effective_lat, longitude=effective_lon, uid=uid)
            return json.dumps({"source": "nearby_places", "confirmed_presence": False,
                               "places": [poi.model_dump(mode="json") for poi in pois[:5]]})
        except Exception as exc:
            return f"Places lookup error: {exc}"

    @tool
    def match_vibration_signature(features: str | dict | None = None,
                                  dominant_frequency_hz: float | None = None, rms_energy: float | None = None,
                                  spectral_entropy: float | None = None) -> str:
        """Inspect measured IMU features against spectral baselines; absent data remains uncertain."""
        measurements = dict(features) if isinstance(features, dict) else {}
        for key, value in (("dominant_frequency_hz", dominant_frequency_hz), ("rms_energy", rms_energy),
                           ("spectral_entropy", spectral_entropy)):
            if value is not None:
                measurements[key] = value
        return json.dumps(vibration_evidence(measurements))

    @tool
    def check_saved_geofences(lat: float | None = None, lon: float | None = None,
                              latitude: float | None = None, longitude: float | None = None) -> str:
        """Check explicit coordinates against this user's saved places with shared reminder geometry."""
        matches = service.saved_geofences(latitude if latitude is not None else lat, longitude if longitude is not None else lon)
        if not matches:
            return "User has no saved places defined."
        if all(match["status"] != "ok" for match in matches):
            return "Geofence check uncertain: explicit valid coordinates are required."
        lines = []
        for match in matches:
            if match["status"] != "ok":
                continue
            if match["inside"]:
                lines.append(f"INSIDE GEOFENCE: '{match['name']}' ({match['category']}), {match['distance_m']:.0f}m from center.")
            elif match["distance_m"] <= match["radius_m"] * 3:
                lines.append(f"NEARBY GEOFENCE: '{match['name']}' ({match['category']}), {match['distance_m']:.0f}m away.")
        return "\n".join(lines) if lines else "GPS is not currently within any saved user geofence."

    @tool
    def check_user_geofences(latitude: float | None = None, longitude: float | None = None,
                             lat: float | None = None, lon: float | None = None) -> str:
        """Alias for check_saved_geofences using the same scoped domain service."""
        return check_saved_geofences.invoke({"latitude": latitude if latitude is not None else lat,
                                            "longitude": longitude if longitude is not None else lon})

    return [get_current_context, get_motion_evidence, get_monitoring_status, check_geofence,
            preview_reminder_match, lookup_nearby_places, match_vibration_signature,
            check_saved_geofences, check_user_geofences]
