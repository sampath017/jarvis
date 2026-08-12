"""Scenario definitions and script builders for Jarvis simulation sessions."""

from __future__ import annotations

from datetime import timedelta

from src.constants import (
    GYM_COORDS,
    HOME_COORDS,
    MIDWAY_COORDS,
    OFFICE_COORDS,
    PARK_COORDS,
    STORE_COORDS,
)
from src.models import ActivityEvent, ChatTurn


# ── Event Construction Helpers ──────────────────────────────────────────────

def _event(
    minutes: int,
    activity: str,
    latitude: float,
    longitude: float,
    speed_mps: float,
    *,
    accuracy_m: float = 8.0,
    vehicle_class_hint: str | None = None,
    classification_confidence: float = 0.0,
    note: str,
) -> ActivityEvent:
    return ActivityEvent(
        offset=timedelta(minutes=minutes),
        activity=activity,
        latitude=latitude,
        longitude=longitude,
        speed_mps=speed_mps,
        accuracy_m=accuracy_m,
        vehicle_class_hint=vehicle_class_hint,
        classification_confidence=classification_confidence,
        note=note,
    )


def _vehicle_event(
    minutes: int,
    latitude: float,
    longitude: float,
    speed_mps: float,
    note: str,
    *,
    vehicle_class_hint: str = "HUNTER_350",
    confidence: float = 0.95,
    accuracy_m: float = 8.0,
) -> ActivityEvent:
    return _event(
        minutes,
        "IN_VEHICLE",
        latitude,
        longitude,
        speed_mps,
        accuracy_m=accuracy_m,
        vehicle_class_hint=vehicle_class_hint,
        classification_confidence=confidence,
        note=note,
    )


# ── 5 Main Comprehensive Simulation Sessions (>10 min each) ─────────────────

def build_morning_commute_scenario() -> list[ActivityEvent]:
    """Session 1: ~18-minute morning commute testing Tier 1 conflicts and dwelling."""
    return [
        _event(0, "STILL", *HOME_COORDS, 0.0, note="Stationary at home baseline"),
        _event(1, "WALKING", 12.971750, 77.594720, 1.1, note="Walks to motorcycle; non-vehicle activity"),
        _vehicle_event(3, 12.971599, 77.594563, 11.5, "Starts Hunter 350 ride; starts mobility session"),
        _vehicle_event(5, 12.969700, 77.602000, 13.0, "Tier 1 test: low confidence fingerprint (0.45)", confidence=0.45),
        _vehicle_event(7, 12.968000, 77.604000, 0.2, "Tier 1 test: stationary GPS speed (0.2 m/s) with high vehicle confidence", confidence=0.95),
        _vehicle_event(9, 12.975000, 77.590000, 10.0, "Tier 1 test: poor GPS accuracy (85m)", accuracy_m=85.0),
        _vehicle_event(10, 12.985000, 77.580000, 12.5, "Normal ride continuation toward office"),
        _event(11, "STILL", *OFFICE_COORDS, 0.0, note="Parks at office parking; pauses session and starts dwell timer"),
        _event(13, "STILL", *OFFICE_COORDS, 0.0, note="Dwells at office parking; tests idempotent pause"),
        _event(15, "WALKING", 12.998900, 77.570300, 1.0, note="Walks into office building; session remains paused"),
        _event(18, "STILL", *OFFICE_COORDS, 0.0, note="Settles at office desk; extended dwell"),
    ]


def build_life_admin_full_script() -> list[ActivityEvent | ChatTurn]:
    """Session 2: ~22-minute life-admin testing Tier 2 LLM CRUD, notes, reminders, and rules."""
    return [
        _event(0, "STILL", *HOME_COORDS, 0.0, note="At home before starting morning routine"),
        ChatTurn("Save my current location as Home.", "Save home place"),
        ChatTurn("Create a note titled Grocery list: buy eggs, almond milk, and sourdough bread.", "Create grocery note"),
        ChatTurn("Create a note titled Project review: finalize Q3 architecture diagram.", "Create project review note"),
        ChatTurn("Remind me to buy groceries the next time I reach the supermarket.", "Create geofence reminder for supermarket"),
        ChatTurn("Create a reminder to do posture check every time I start walking.", "Create activity reminder"),
        ChatTurn("Remind me to submit the daily summary report tonight.", "Create time reminder"),
        ChatTurn("When I arrive at the gym, add 'refilled water bottle' to the Project review note.", "Create GEOFENCE + APPEND_NOTE rule"),
        ChatTurn("When I start walking, send me a notification saying 'remember to stay hydrated'.", "Create ACTIVITY + NOTIFY rule"),
        _event(8, "WALKING", *MIDWAY_COORDS, 1.2, note="Leaves home on foot; activity triggers walking reminder and rule"),
        _event(12, "WALKING", *GYM_COORDS, 1.1, note="Arrives at gym; geofence triggers append-note context rule"),
        ChatTurn("Save my current location as Gym.", "Save gym place"),
        ChatTurn("Update the Grocery list note to add greek yogurt and apples.", "Update note by title"),
        ChatTurn("Change the posture check reminder so it says 'posture check and deep breath'.", "Update reminder by title"),
        ChatTurn("List my notes.", "List notes via Tier 2"),
        ChatTurn("List my active reminders.", "List active reminders"),
        ChatTurn("Show my pending notifications.", "List pending notifications"),
        ChatTurn("Mark the posture check reminder completed.", "Complete reminder by title"),
        _event(18, "WALKING", *MIDWAY_COORDS, 1.2, note="Walks back toward home"),
        _event(22, "WALKING", *HOME_COORDS, 1.0, note="Returns home"),
        ChatTurn("Delete the Project review note.", "Delete note by title"),
        ChatTurn("List my context rules.", "List active context rules"),
    ]


def build_session_lifecycle_scenario() -> list[ActivityEvent]:
    """Session 3: ~60-minute session lifecycle testing 30-min TTL boundaries, dwell, and expiry."""
    return [
        _vehicle_event(0, *HOME_COORDS, 12.0, "Starts Hunter 350 ride; creates mobility session (ACTIVE)"),
        _vehicle_event(3, 12.969700, 77.602000, 14.0, "Cruising along the primary route (ACTIVE)"),
        _event(6, "STILL", *STORE_COORDS, 0.0, note="Stops at first shop; session transitions to PAUSED"),
        _event(9, "STILL", *STORE_COORDS, 0.0, note="Dwelling at first shop; verifies idempotent PAUSED state"),
        _vehicle_event(14, *STORE_COORDS, 6.0, "Resumes ride after 8 min (<30 min TTL); session resumes (ACTIVE)"),
        _vehicle_event(17, 12.969300, 77.602300, 11.0, "Cruising toward second destination (ACTIVE)"),
        _event(20, "STILL", *OFFICE_COORDS, 0.0, note="Parks at office; session transitions to PAUSED"),
        _event(22, "WALKING", 12.998900, 77.570300, 1.1, note="Walks around office campus; session remains PAUSED"),
        _event(25, "STILL", *OFFICE_COORDS, 0.0, note="Dwelling in meeting room; session still PAUSED"),
        # Virtual jump to 55 minutes: 35 minutes after the 20-min pause event (exceeds 30-min TTL)
        _vehicle_event(55, *OFFICE_COORDS, 8.0, "Starts riding after 35 min dwell (>30 min TTL); closes expired session and starts NEW session"),
        _vehicle_event(58, 12.980000, 77.585000, 12.0, "Cruising on new session (ACTIVE)"),
        _event(60, "STILL", *HOME_COORDS, 0.0, note="Parks back at home; new session transitions to PAUSED"),
    ]


def build_edge_cases_extended_scenario() -> list[ActivityEvent]:
    """Session 4: ~15-minute test covering all vehicle classes and conflict edge cases."""
    return [
        _event(0, "IN_VEHICLE", *HOME_COORDS, 9.0, vehicle_class_hint="HUNTER_350",
               classification_confidence=0.40, note="Tier 1: low-confidence vehicle fingerprint (0.40)"),
        _event(2, "IN_VEHICLE", 12.971800, 77.595000, 0.1, vehicle_class_hint="HUNTER_350",
               classification_confidence=0.95, note="Tier 1: stationary GPS speed (0.1 m/s) with high vehicle confidence"),
        _event(4, "IN_VEHICLE", 12.972100, 77.595500, 8.0, accuracy_m=90.0,
               vehicle_class_hint="HUNTER_350", classification_confidence=0.95,
               note="Tier 1: poor GPS accuracy (90m)"),
        _event(6, "IN_VEHICLE", 12.972500, 77.596000, 7.0, vehicle_class_hint="NOT_VEHICLE",
               classification_confidence=0.99, note="Definitive NOT_VEHICLE fingerprint; must NOT create session or trigger Tier 1"),
        _event(8, "IN_VEHICLE", 12.973000, 77.597000, 15.0, vehicle_class_hint="CAR",
               classification_confidence=0.92, note="CAR vibration profile; creates CAR mobility session"),
        _event(10, "IN_VEHICLE", 12.974000, 77.598000, 8.0, vehicle_class_hint="BUS",
               classification_confidence=0.88, note="BUS vibration profile; handles vehicle transition"),
        _event(12, "IN_VEHICLE", 12.975000, 77.599000, 12.0, vehicle_class_hint="OTHER_MOTORCYCLE",
               classification_confidence=0.85, note="Generic OTHER_MOTORCYCLE fingerprint"),
        _event(15, "STILL", *HOME_COORDS, 0.0, note="Final stationary event; pauses session without vehicle fingerprint"),
    ]


def build_context_rules_deep_script() -> list[ActivityEvent | ChatTurn]:
    """Session 5: ~20-minute deep test for all context rule action types, triggers, and one_shot."""
    return [
        _event(0, "STILL", *HOME_COORDS, 0.0, note="At home baseline"),
        ChatTurn("Create a note titled Journey log: starting the day with high energy.", "Setup note for APPEND_NOTE rule"),
        ChatTurn("Create a reminder to check tyre pressure, active, not one-shot.", "Setup reminder for UPDATE_REMINDER rule"),
        ChatTurn("When I arrive at the gym, add 'checked in at gym reception' to the Journey log.", "Rule 1: GEOFENCE + APPEND_NOTE"),
        ChatTurn("When I start walking, send a notification saying 'maintain a good walking pace'.", "Rule 2: ACTIVITY + NOTIFY"),
        ChatTurn("When I arrive at the office, update my tyre pressure reminder to say 'tyre pressure verified ok'.", "Rule 3: GEOFENCE + UPDATE_REMINDER"),
        ChatTurn("Create a one-shot context rule: when I arrive at the park, notify me 'welcome to the park'.", "Rule 4: GEOFENCE + NOTIFY (one-shot)"),
        _event(5, "WALKING", *MIDWAY_COORDS, 1.2, note="Leaves home; ACTIVITY_ENTER triggers Rule 2 (walk notification)"),
        _event(8, "WALKING", *GYM_COORDS, 1.1, note="Arrives at gym; GEOFENCE_ENTER triggers Rule 1 (append note to Journey log)"),
        _event(10, "WALKING", *MIDWAY_COORDS, 1.2, note="Leaves gym; exits gym geofence"),
        _event(12, "WALKING", *GYM_COORDS, 1.1, note="Re-enters gym geofence; Rule 1 fires again (recurring rule)"),
        _event(14, "WALKING", *OFFICE_COORDS, 1.0, note="Arrives at office; GEOFENCE_ENTER triggers Rule 3 (update reminder)"),
        _event(16, "WALKING", *PARK_COORDS, 1.0, note="Arrives at park; GEOFENCE_ENTER triggers Rule 4 (one-shot notify and auto-disables)"),
        _event(18, "WALKING", *MIDWAY_COORDS, 1.2, note="Leaves park; exits park geofence"),
        _event(20, "WALKING", *PARK_COORDS, 1.0, note="Re-enters park; Rule 4 is one-shot disabled and must NOT fire again"),
        ChatTurn("List my notes.", "Verify Journey log has appended entries"),
        ChatTurn("Show my pending notifications.", "Verify notification outbox"),
        ChatTurn("List my context rules.", "Verify one-shot rule shows disabled"),
    ]


# ── Backward-Compatible Scenario Routing ────────────────────────────────────

ALL_SCENARIOS = (
    # 5 Main Comprehensive Sessions (>10 min each)
    ("morning-commute", "18-min commute: Tier 1 conflicts, GPS accuracy, session start/pause/dwell"),
    ("life-admin-full", "22-min full Tier 2: notes, reminders, rules, outbox notifications"),
    ("session-lifecycle", "60-min TTL lifecycle: start, pause, resume in TTL, dwell, 30-min expiry"),
    ("edge-cases-extended", "15-min edge cases: all vehicle classes, low confidence, stationary conflict"),
    ("context-rules-deep", "20-min deep rules: NOTIFY, APPEND_NOTE, UPDATE_REMINDER, one_shot, re-entry"),
    # Shorthand & legacy aliases
    ("hunter-return", "Alias for morning-commute"),
    ("life-admin-llm", "Alias for life-admin-full"),
    ("edge-cases", "Alias for edge-cases-extended"),
    ("walking", "Short non-vehicle walking scenario"),
    ("signal-gap-return", "20-min telemetry gap within 30-min TTL"),
    ("ttl-expiry", "Return after 37 minutes (>30-min TTL)"),
)

CHAT_SCENARIOS = frozenset({"life-admin-full", "life-admin-llm", "context-rules-deep"})


def build_scenario(name: str) -> list[ActivityEvent]:
    """Return a virtual event timeline for a named test case."""
    if name in ("morning-commute", "hunter-return"):
        return build_morning_commute_scenario()
    if name == "session-lifecycle":
        return build_session_lifecycle_scenario()
    if name in ("edge-cases-extended", "edge-cases"):
        return build_edge_cases_extended_scenario()
    if name == "walking":
        return [
            _event(0, "STILL", *HOME_COORDS, 0.0, note="Stationary baseline"),
            _event(1, "WALKING", 12.971750, 77.594720, 1.1, note="Short walk"),
            _event(5, "WALKING", 12.972100, 77.595100, 1.2, note="Continues walking"),
            _event(12, "STILL", *HOME_COORDS, 0.0, note="Returns and rests"),
        ]
    if name == "signal-gap-return":
        return [
            _vehicle_event(0, *HOME_COORDS, 10.5, "Starts a journey"),
            _event(8, "STILL", *STORE_COORDS, 0.0, note="Parks before simulated signal loss"),
            _vehicle_event(28, *STORE_COORDS, 5.5, "Returns after a 20-minute data gap, still inside TTL"),
        ]
    if name == "ttl-expiry":
        return [
            _vehicle_event(0, *HOME_COORDS, 10.5, "Starts a journey"),
            _event(8, "STILL", *STORE_COORDS, 0.0, note="Parks the vehicle"),
            _vehicle_event(45, *STORE_COORDS, 5.5, "Returns 37 minutes later, beyond the 30-minute TTL"),
        ]
    raise ValueError(f"Unknown scenario '{name}'. Use --list-scenarios to see available names.")


def build_chat_script(name: str) -> list[ActivityEvent | ChatTurn]:
    """Return a combined chat + context script for a named scenario."""
    if name in ("life-admin-full", "life-admin-llm"):
        return build_life_admin_full_script()
    if name == "context-rules-deep":
        return build_context_rules_deep_script()
    raise ValueError(f"Unknown chat script scenario '{name}'. Use --list-scenarios to see available names.")
