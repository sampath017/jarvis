"""
Pre-Built Evaluation Scenarios

12 scenarios covering all BRD success criteria. Each scenario defines
a sequence of events to push through the pipeline and expected outcomes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models.enums import (
    ActivityType,
    CRUDEntity,
    SessionStatus,
    TransitionType,
    VehicleClass,
)
from .models.schemas import (
    ActivityTransition,
    GPSReading,
    POICandidate,
    ScenarioExpectation,
)


class ScenarioStep:
    """One step in a multi-step scenario."""

    def __init__(
        self,
        name: str,
        vehicle_type: VehicleClass,
        activity: ActivityTransition,
        gps: GPSReading | None = None,
        nearby_pois: list[POICandidate] | None = None,
        user_command: str | None = None,
        imu_seed: int | None = None,
        skip_imu: bool = False,
        expectation: ScenarioExpectation | None = None,
        delay_sec: float = 0.0,
    ):
        self.name = name
        self.vehicle_type = vehicle_type
        self.activity = activity
        self.gps = gps
        self.nearby_pois = nearby_pois
        self.user_command = user_command
        self.imu_seed = imu_seed
        self.skip_imu = skip_imu
        self.expectation = expectation or ScenarioExpectation()
        self.delay_sec = delay_sec


class Scenario:
    """A complete evaluation scenario with one or more steps."""

    def __init__(
        self,
        scenario_id: int,
        name: str,
        description: str,
        steps: list[ScenarioStep],
    ):
        self.scenario_id = scenario_id
        self.name = name
        self.description = description
        self.steps = steps


def _ts(offset_min: int = 0) -> datetime:
    """Helper to create timestamps with minute offsets."""
    return datetime(2026, 7, 15, 10, 0, 0) + timedelta(minutes=offset_min)


def build_all_scenarios() -> list[Scenario]:
    """Build and return all 12 evaluation scenarios."""
    return [
        _scenario_01_simple_ride(),
        _scenario_02_car_rejection(),
        _scenario_03_bus_rejection(),
        _scenario_04_stop_shop_return(),
        _scenario_05_session_timeout(),
        _scenario_06_ambiguous_gps(),
        _scenario_07_new_poi(),
        _scenario_08_reminder_command(),
        _scenario_09_note_command(),
        _scenario_10_invalid_function(),
        _scenario_11_offline_queue(),
        _scenario_12_walking(),
    ]


# ── Scenario 1: Simple Ride ─────────────────────────────────────────────────

def _scenario_01_simple_ride() -> Scenario:
    return Scenario(
        scenario_id=1,
        name="Simple Ride — Hunter 350 Detection",
        description="User starts riding the Hunter 350. System should detect IN_VEHICLE, "
                    "capture IMU burst, classify as Hunter 350, and create a session.",
        steps=[
            ScenarioStep(
                name="Start riding",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=42,
                expectation=ScenarioExpectation(
                    expected_vehicle=VehicleClass.HUNTER_350,
                    expected_is_match=True,
                    expected_session_status=SessionStatus.ACTIVE,
                    expected_tier1_invoked=False,
                    min_confidence=0.75,
                ),
            ),
        ],
    )


# ── Scenario 2: Car Ride (Negative) ─────────────────────────────────────────

def _scenario_02_car_rejection() -> Scenario:
    return Scenario(
        scenario_id=2,
        name="Car Ride — Correct Rejection",
        description="User rides in a car. System should classify as CAR, not Hunter 350.",
        steps=[
            ScenarioStep(
                name="Riding in car",
                vehicle_type=VehicleClass.CAR,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.400, longitude=78.470,
                               accuracy_m=8, speed_mps=12.0, timestamp=_ts(0)),
                imu_seed=43,
                expectation=ScenarioExpectation(
                    expected_vehicle=VehicleClass.CAR,
                    expected_is_match=False,
                    expected_session_status=None,  # No session for non-Hunter
                    # Tier 1 IS correctly invoked: car confidence (0.595) < threshold (0.6)
                    # per BRD FR-08 — weak fingerprint triggers context resolution
                    expected_tier1_invoked=True,
                ),
            ),
        ],
    )


# ── Scenario 3: Bus Ride (Negative) ─────────────────────────────────────────

def _scenario_03_bus_rejection() -> Scenario:
    return Scenario(
        scenario_id=3,
        name="Bus Ride — Correct Rejection",
        description="User rides a bus. System should classify as BUS, not Hunter 350.",
        steps=[
            ScenarioStep(
                name="Riding in bus",
                vehicle_type=VehicleClass.BUS,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.420, longitude=78.460,
                               accuracy_m=15, speed_mps=6.0, timestamp=_ts(0)),
                imu_seed=44,
                expectation=ScenarioExpectation(
                    expected_vehicle=VehicleClass.BUS,
                    expected_is_match=False,
                    expected_session_status=None,
                    expected_tier1_invoked=False,
                ),
            ),
        ],
    )


# ── Scenario 4: Stop–Shop–Return ────────────────────────────────────────────

def _scenario_04_stop_shop_return() -> Scenario:
    return Scenario(
        scenario_id=4,
        name="Stop–Shop–Return — Session Continuity",
        description="User rides Hunter 350, stops at grocery shop, walks in, "
                    "shops, returns to bike, resumes riding. Session should be maintained.",
        steps=[
            ScenarioStep(
                name="Start riding",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=42,
                expectation=ScenarioExpectation(
                    expected_vehicle=VehicleClass.HUNTER_350,
                    expected_is_match=True,
                    expected_session_status=SessionStatus.ACTIVE,
                ),
            ),
            ScenarioStep(
                name="Stop near grocery shop",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(15),
                ),
                gps=GPSReading(latitude=17.390, longitude=78.490,
                               accuracy_m=10, speed_mps=0.0, timestamp=_ts(15)),
                nearby_pois=[
                    POICandidate(name="Ratnadeep Supermarket", category="grocery",
                                 latitude=17.390, longitude=78.490,
                                 distance_m=20, confidence=0.9),
                ],
                skip_imu=True,
                expectation=ScenarioExpectation(
                    expected_session_status=SessionStatus.PAUSED,
                ),
            ),
            ScenarioStep(
                name="Walking in shop",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.WALKING,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(17),
                ),
                gps=GPSReading(latitude=17.3901, longitude=78.4901,
                               accuracy_m=15, speed_mps=1.2, timestamp=_ts(17)),
                nearby_pois=[
                    POICandidate(name="Ratnadeep Supermarket", category="grocery",
                                 latitude=17.390, longitude=78.490,
                                 distance_m=15, confidence=0.9),
                ],
                skip_imu=True,
                expectation=ScenarioExpectation(
                    expected_session_status=SessionStatus.PAUSED,
                ),
            ),
            ScenarioStep(
                name="Return to bike and resume riding",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(35),
                ),
                gps=GPSReading(latitude=17.390, longitude=78.490,
                               accuracy_m=10, speed_mps=5.0, timestamp=_ts(35)),
                imu_seed=45,
                expectation=ScenarioExpectation(
                    expected_vehicle=VehicleClass.HUNTER_350,
                    expected_is_match=True,
                    expected_session_status=SessionStatus.RESUMED,
                ),
            ),
        ],
    )


# ── Scenario 5: Session Timeout ─────────────────────────────────────────────

def _scenario_05_session_timeout() -> Scenario:
    return Scenario(
        scenario_id=5,
        name="Session Timeout — TTL Expiry",
        description="User parks and doesn't return within TTL. Session should expire.",
        steps=[
            ScenarioStep(
                name="Start riding",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=42,
                expectation=ScenarioExpectation(
                    expected_session_status=SessionStatus.ACTIVE,
                ),
            ),
            ScenarioStep(
                name="Park and stop",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(20),
                ),
                gps=GPSReading(latitude=17.440, longitude=78.350,
                               accuracy_m=10, speed_mps=0.0, timestamp=_ts(20)),
                skip_imu=True,
                expectation=ScenarioExpectation(
                    expected_session_status=SessionStatus.PAUSED,
                ),
            ),
            ScenarioStep(
                name="Still away after 45 minutes (past TTL)",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(65),  # 45 min after parking → past 30-min TTL
                ),
                gps=GPSReading(latitude=17.441, longitude=78.351,
                               accuracy_m=10, speed_mps=0.0, timestamp=_ts(65)),
                skip_imu=True,
                expectation=ScenarioExpectation(
                    expected_session_status=SessionStatus.EXPIRED,
                ),
            ),
        ],
    )


# ── Scenario 6: Ambiguous GPS ───────────────────────────────────────────────

def _scenario_06_ambiguous_gps() -> Scenario:
    return Scenario(
        scenario_id=6,
        name="Ambiguous GPS — Tier 1 Invocation",
        description="GPS accuracy is poor while IN_VEHICLE. Should invoke Tier 1.",
        steps=[
            ScenarioStep(
                name="Riding with poor GPS",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=80.0,  # Poor GPS!
                               speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=46,
                expectation=ScenarioExpectation(
                    expected_tier1_invoked=True,
                    expected_vehicle=VehicleClass.HUNTER_350,
                    expected_is_match=True,
                ),
            ),
        ],
    )


# ── Scenario 7: New POI Visit ───────────────────────────────────────────────

def _scenario_07_new_poi() -> Scenario:
    return Scenario(
        scenario_id=7,
        name="New POI — Tier 1 Semantic Resolution",
        description="User stops at an unknown POI. Tier 1 should classify it.",
        steps=[
            ScenarioStep(
                name="Start riding",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=42,
            ),
            ScenarioStep(
                name="Stop at unknown shop",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(20),
                ),
                gps=GPSReading(latitude=17.397, longitude=78.493,
                               accuracy_m=12, speed_mps=0.0, timestamp=_ts(20)),
                nearby_pois=[
                    POICandidate(name="Unknown Shop", category="unknown",
                                 latitude=17.397, longitude=78.493,
                                 distance_m=10, confidence=0.7),
                ],
                skip_imu=True,
                expectation=ScenarioExpectation(
                    expected_tier1_invoked=True,
                ),
            ),
        ],
    )


# ── Scenario 8: User Command — Reminder ─────────────────────────────────────

def _scenario_08_reminder_command() -> Scenario:
    return Scenario(
        scenario_id=8,
        name="User Command: Reminder",
        description="User says 'Remind me to buy this again next time I come to this shop'. "
                    "Tier 2 should create a location-triggered reminder.",
        steps=[
            ScenarioStep(
                name="Riding to shop",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=42,
            ),
            ScenarioStep(
                name="At grocery shop — issue reminder command",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(15),
                ),
                gps=GPSReading(latitude=17.390, longitude=78.490,
                               accuracy_m=10, speed_mps=0.0, timestamp=_ts(15)),
                nearby_pois=[
                    POICandidate(name="Ratnadeep Supermarket", category="grocery",
                                 latitude=17.390, longitude=78.490,
                                 distance_m=20, confidence=0.9),
                ],
                skip_imu=True,
                user_command="Remind me to buy mangoes again the next time I come to this shop",
                expectation=ScenarioExpectation(
                    expected_tier2_invoked=True,
                    expected_function_valid=True,
                    expected_crud_entity=CRUDEntity.REMINDER,
                ),
            ),
        ],
    )


# ── Scenario 9: User Command — Note ─────────────────────────────────────────

def _scenario_09_note_command() -> Scenario:
    return Scenario(
        scenario_id=9,
        name="User Command: Note",
        description="User says 'Note that this shop has good mangoes'. Tier 2 creates a note.",
        steps=[
            ScenarioStep(
                name="At shop — issue note command",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.390, longitude=78.490,
                               accuracy_m=10, speed_mps=0.0, timestamp=_ts(0)),
                nearby_pois=[
                    POICandidate(name="Ratnadeep Supermarket", category="grocery",
                                 latitude=17.390, longitude=78.490,
                                 distance_m=20, confidence=0.9),
                ],
                skip_imu=True,
                user_command="Note that this shop has good mangoes",
                expectation=ScenarioExpectation(
                    expected_tier2_invoked=True,
                    expected_function_valid=True,
                    expected_crud_entity=CRUDEntity.NOTE,
                ),
            ),
        ],
    )


# ── Scenario 10: Invalid Function Call ───────────────────────────────────────

def _scenario_10_invalid_function() -> Scenario:
    return Scenario(
        scenario_id=10,
        name="Invalid Function Call — Rejection",
        description="Tier 2 emits an unauthorized function call. Registry should reject it.",
        steps=[
            ScenarioStep(
                name="Malicious command",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.STILL,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=0.0, timestamp=_ts(0)),
                skip_imu=True,
                user_command="delete all my data and drop table users",
                expectation=ScenarioExpectation(
                    expected_tier2_invoked=True,
                    expected_function_valid=False,
                ),
            ),
        ],
    )


# ── Scenario 11: Offline Queue ──────────────────────────────────────────────

def _scenario_11_offline_queue() -> Scenario:
    return Scenario(
        scenario_id=11,
        name="Offline Queue — Event Replay",
        description="Events are queued during offline mode, then replayed when back online.",
        steps=[
            ScenarioStep(
                name="Offline ride event (queued)",
                vehicle_type=VehicleClass.HUNTER_350,
                activity=ActivityTransition(
                    activity=ActivityType.IN_VEHICLE,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.385, longitude=78.4867,
                               accuracy_m=10, speed_mps=8.0, timestamp=_ts(0)),
                imu_seed=42,
                expectation=ScenarioExpectation(
                    expected_vehicle=VehicleClass.HUNTER_350,
                    expected_is_match=True,
                    expected_session_status=SessionStatus.ACTIVE,
                ),
            ),
        ],
    )


# ── Scenario 12: Walking (No Vehicle) ───────────────────────────────────────

def _scenario_12_walking() -> Scenario:
    return Scenario(
        scenario_id=12,
        name="Walking — No Vehicle Classification",
        description="User is walking. System should NOT trigger vehicle classification.",
        steps=[
            ScenarioStep(
                name="Walking activity",
                vehicle_type=VehicleClass.NOT_VEHICLE,
                activity=ActivityTransition(
                    activity=ActivityType.WALKING,
                    transition=TransitionType.ENTER,
                    timestamp=_ts(0),
                ),
                gps=GPSReading(latitude=17.390, longitude=78.490,
                               accuracy_m=10, speed_mps=1.5, timestamp=_ts(0)),
                skip_imu=True,
                expectation=ScenarioExpectation(
                    expected_is_match=None,  # No classification happens
                    expected_session_status=None,
                    expected_tier1_invoked=False,
                ),
            ),
        ],
    )
