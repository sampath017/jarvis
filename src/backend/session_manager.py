"""
FR-06/FR-07: Journey Session State Machine (Stop–Shop–Return)

Maintains journey continuity across park → walk → shop → return transitions.
Uses a deterministic state machine with configurable TTL.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..config import (
    MAX_SPEED_WALKING_MPS,
    MIN_DWELL_SEC,
    PARKING_RADIUS_M,
    SESSION_TTL_SEC,
)
from ..models.enums import ActivityType, SessionStatus, VehicleClass
from ..models.schemas import (
    ActivityTransition,
    ClassificationResult,
    ContextPacket,
    GPSReading,
    POICandidate,
    SessionState,
)


class SessionManager:
    """
    Manages journey sessions using the Stop–Shop–Return state machine.

    State transitions:
        CREATED → ACTIVE → PAUSED → RESUMED → COMPLETED
                     ↓         ↓
                  COMPLETED  EXPIRED (after TTL)
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._active_session_id: str | None = None

    @property
    def active_session(self) -> SessionState | None:
        if self._active_session_id and self._active_session_id in self._sessions:
            return self._sessions[self._active_session_id]
        return None

    @property
    def all_sessions(self) -> list[SessionState]:
        return list(self._sessions.values())

    def process_event(self, packet: ContextPacket) -> SessionState | None:
        """
        Process a context packet through the state machine.
        Returns the updated (or newly created) session, or None.
        """
        now = packet.timestamp

        # Check for TTL expiry on any paused session
        self._check_expiry(now)

        activity = packet.activity_transition
        classification = packet.classification
        gps = packet.gps
        pois = packet.nearby_pois

        # ── Determine what action to take ────────────────────────────────
        current = self.active_session

        if current is None:
            # No active session → check if we should start one
            if self._should_start_session(activity, classification):
                return self._create_session(packet)
            return None

        status = current.status

        if status in (SessionStatus.ACTIVE, SessionStatus.RESUMED):
            # Currently riding → check for stop/park
            if self._is_stopping(activity, gps):
                return self._pause_session(current, packet)
            elif self._is_completing(activity, classification):
                return self._complete_session(current, packet)
            else:
                # Update session with new event
                return self._update_session(current, packet)

        elif status == SessionStatus.PAUSED:
            # Currently paused → check for return or completion
            if self._is_returning(activity, classification, gps, current):
                return self._resume_session(current, packet)
            elif self._should_record_dwell(pois, current, now):
                return self._record_poi_visit(current, packet)
            else:
                return self._update_session(current, packet)

        return current

    def force_complete(self, session_id: str | None = None) -> SessionState | None:
        """Force-complete a session (used by Tier 1 when it recommends COMPLETE)."""
        sid = session_id or self._active_session_id
        if sid and sid in self._sessions:
            session = self._sessions[sid]
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now()
            session.last_updated = datetime.now()
            if self._active_session_id == sid:
                self._active_session_id = None
            return session
        return None

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    # ── Private: State transition methods ────────────────────────────────

    def _create_session(self, packet: ContextPacket) -> SessionState:
        session = SessionState(
            status=SessionStatus.ACTIVE,
            vehicle_class=(packet.classification.vehicle_class
                           if packet.classification else VehicleClass.UNKNOWN),
            started_at=packet.timestamp,
            last_updated=packet.timestamp,
            classification_confidence=(packet.classification.confidence
                                       if packet.classification else 0.0),
        )
        session.events.append(packet.event_id)
        self._sessions[session.session_id] = session
        self._active_session_id = session.session_id
        return session

    def _pause_session(
        self, session: SessionState, packet: ContextPacket
    ) -> SessionState:
        session.status = SessionStatus.PAUSED
        session.paused_at = packet.timestamp
        session.last_updated = packet.timestamp
        session.parking_gps = packet.gps
        session.events.append(packet.event_id)
        return session

    def _resume_session(
        self, session: SessionState, packet: ContextPacket
    ) -> SessionState:
        session.status = SessionStatus.RESUMED
        session.last_updated = packet.timestamp
        session.paused_at = None
        session.resume_count += 1
        session.events.append(packet.event_id)
        if packet.classification:
            session.classification_confidence = packet.classification.confidence
        return session

    def _complete_session(
        self, session: SessionState, packet: ContextPacket
    ) -> SessionState:
        session.status = SessionStatus.COMPLETED
        session.completed_at = packet.timestamp
        session.last_updated = packet.timestamp
        session.events.append(packet.event_id)
        self._active_session_id = None
        return session

    def _update_session(
        self, session: SessionState, packet: ContextPacket
    ) -> SessionState:
        session.last_updated = packet.timestamp
        session.events.append(packet.event_id)
        return session

    def _record_poi_visit(
        self, session: SessionState, packet: ContextPacket
    ) -> SessionState:
        if packet.nearby_pois:
            session.poi_visits.extend(packet.nearby_pois)
        session.last_updated = packet.timestamp
        session.events.append(packet.event_id)
        return session

    def _check_expiry(self, now: datetime) -> None:
        """Expire any paused sessions past TTL."""
        for session in self._sessions.values():
            if (session.status == SessionStatus.PAUSED
                    and session.paused_at
                    and (now - session.paused_at).total_seconds() > SESSION_TTL_SEC):
                session.status = SessionStatus.EXPIRED
                session.completed_at = now
                session.last_updated = now
                if self._active_session_id == session.session_id:
                    self._active_session_id = None

    # ── Private: Condition checks ────────────────────────────────────────

    def _should_start_session(
        self,
        activity: ActivityTransition | None,
        classification: ClassificationResult | None,
    ) -> bool:
        """Start a session when we detect IN_VEHICLE with Hunter 350 match."""
        if activity and activity.activity == ActivityType.IN_VEHICLE:
            if classification and classification.is_match:
                return True
        return False

    def _is_stopping(
        self,
        activity: ActivityTransition | None,
        gps: GPSReading | None,
    ) -> bool:
        """Detect transition from riding to stopped/walking."""
        if activity and activity.activity in (ActivityType.STILL, ActivityType.WALKING):
            return True
        if gps and gps.speed_mps < MAX_SPEED_WALKING_MPS:
            # Might be slowing down — but only if activity also suggests stop
            pass
        return False

    def _is_completing(
        self,
        activity: ActivityTransition | None,
        classification: ClassificationResult | None,
    ) -> bool:
        """Detect explicit journey end (e.g., long STILL without return)."""
        # This is handled more by TTL expiry; explicit complete is rare
        return False

    def _is_returning(
        self,
        activity: ActivityTransition | None,
        classification: ClassificationResult | None,
        gps: GPSReading | None,
        session: SessionState,
    ) -> bool:
        """Detect return to vehicle within TTL and parking radius."""
        if not (activity and activity.activity == ActivityType.IN_VEHICLE):
            return False
        if not (classification and classification.is_match):
            return False

        # Check proximity to parking location
        if session.parking_gps and gps:
            dist = _haversine_m(
                session.parking_gps.latitude, session.parking_gps.longitude,
                gps.latitude, gps.longitude,
            )
            if dist > PARKING_RADIUS_M:
                return False

        return True

    def _should_record_dwell(
        self,
        pois: list[POICandidate],
        session: SessionState,
        now: datetime,
    ) -> bool:
        """Check if there's a POI visit worth recording during a pause."""
        if not pois:
            return False
        if session.paused_at:
            dwell = (now - session.paused_at).total_seconds()
            return dwell >= MIN_DWELL_SEC
        return False


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS coordinates in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
