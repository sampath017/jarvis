"""
Deterministic Journey Session State Machine

Maintains journey continuity across park → walk → shop → return transitions.
Uses a deterministic state machine with configurable TTL.

In production, session state is persisted to Firestore. This module contains
the pure state-transition logic; Firestore I/O is handled by the graph nodes.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..settings import (
    MAX_SPEED_WALKING_MPS,
    MIN_DWELL_SEC,
    PARKING_RADIUS_M,
    SESSION_TTL_SEC,
    TIER1_SESSION_PROMOTION_THRESHOLD,
    VEHICLE_HIGH_CONFIDENCE_THRESHOLD,
)
from ..models.enums import ActivityType, SessionStatus, VehicleClass
from ..models.schemas import (
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

    def process_event(
        self,
        packet: ContextPacket,
        current_session: SessionState | None,
    ) -> SessionState | None:
        """
        Process a context packet through the state machine.

        Takes the current session (loaded from Firestore) and returns
        the updated session, a newly created session, or None.
        """
        now = packet.timestamp

        # Check for TTL expiry on paused session
        if current_session:
            current_session = self._check_expiry(current_session, now)

        activity = packet.activity
        confidence = packet.classification_confidence
        vehicle_hint = packet.vehicle_class_hint
        gps = packet.gps
        pois = packet.nearby_pois

        if current_session is None:
            # No active session → check if we should start one
            if self._should_start_session(activity, confidence, vehicle_hint):
                return self._create_session(packet)
            return None

        status = current_session.status

        if status in (SessionStatus.ACTIVE, SessionStatus.RESUMED):
            if self._is_stopping(activity, gps):
                return self._pause_session(current_session, packet)
            else:
                return self._update_session(current_session, packet)

        elif status == SessionStatus.PAUSED:
            if self._is_returning(activity, confidence, vehicle_hint, gps, current_session):
                return self._resume_session(current_session, packet)
            elif self._should_record_dwell(pois, current_session, now):
                return self._record_poi_visit(current_session, packet)
            else:
                return self._update_session(current_session, packet)

        return current_session

    def force_complete(self, session: SessionState) -> SessionState:
        """Force-complete a session (used by Tier 1 when it recommends COMPLETE)."""
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        session.last_updated = datetime.utcnow()
        return session

    def apply_tier1_resolution(
        self,
        packet: ContextPacket,
        current_session: SessionState | None,
        action: str,
        resolved_vehicle: str,
        confidence: float,
    ) -> SessionState | None:
        """Apply a constrained Tier 1 outcome before mutating session state."""
        if action in ("REJECT", "RECLASSIFY"):
            return current_session
        if action == "COMPLETE":
            return self.force_complete(current_session) if current_session else None
        if action == "PAUSE":
            if current_session and current_session.status in (SessionStatus.ACTIVE, SessionStatus.RESUMED):
                return self._pause_session(current_session, packet)
            return current_session

        effective_packet = packet.model_copy(update={
            "vehicle_class_hint": resolved_vehicle,
            "classification_confidence": confidence,
        })
        can_promote = self._is_verified_vehicle(
            effective_packet.activity,
            confidence,
            resolved_vehicle,
            threshold=TIER1_SESSION_PROMOTION_THRESHOLD,
        )

        if action == "RESUME":
            if current_session and current_session.status == SessionStatus.PAUSED and can_promote:
                return self._resume_session(current_session, effective_packet)
            return current_session

        if action == "ACCEPT" and can_promote:
            return self.process_event(effective_packet, current_session)
        return current_session

    # ── Private: State transition methods ────────────────────────────────

    def _create_session(self, packet: ContextPacket) -> SessionState:
        session = SessionState(
            status=SessionStatus.ACTIVE,
            vehicle_class=VehicleClass(packet.vehicle_class_hint)
            if packet.vehicle_class_hint else VehicleClass.UNKNOWN,
            started_at=packet.timestamp,
            last_updated=packet.timestamp,
            classification_confidence=packet.classification_confidence,
        )
        session.events.append(packet.event_id)
        return session

    def _pause_session(
        self, session: SessionState, packet: ContextPacket,
    ) -> SessionState:
        session.status = SessionStatus.PAUSED
        session.paused_at = packet.timestamp
        session.last_updated = packet.timestamp
        session.parking_gps = packet.gps
        session.events.append(packet.event_id)
        return session

    def _resume_session(
        self, session: SessionState, packet: ContextPacket,
    ) -> SessionState:
        session.status = SessionStatus.RESUMED
        session.last_updated = packet.timestamp
        session.paused_at = None
        session.resume_count += 1
        session.events.append(packet.event_id)
        session.classification_confidence = packet.classification_confidence
        return session

    def _update_session(
        self, session: SessionState, packet: ContextPacket,
    ) -> SessionState:
        session.last_updated = packet.timestamp
        session.events.append(packet.event_id)
        return session

    def _record_poi_visit(
        self, session: SessionState, packet: ContextPacket,
    ) -> SessionState:
        if packet.nearby_pois:
            session.poi_visits.extend(packet.nearby_pois)
        session.last_updated = packet.timestamp
        session.events.append(packet.event_id)
        return session

    def _check_expiry(
        self, session: SessionState, now: datetime,
    ) -> SessionState:
        """Expire a paused session past TTL."""
        if (
            session.status == SessionStatus.PAUSED
            and session.paused_at
            and (now - session.paused_at).total_seconds() > SESSION_TTL_SEC
        ):
            session.status = SessionStatus.EXPIRED
            session.completed_at = now
            session.last_updated = now
        return session

    # ── Private: Condition checks ────────────────────────────────────────

    def _should_start_session(
        self, activity: str, confidence: float, vehicle_hint: str,
    ) -> bool:
        """Start a session when we detect IN_VEHICLE with sufficient confidence."""
        return self._is_verified_vehicle(activity, confidence, vehicle_hint)

    def _is_stopping(
        self, activity: str, gps: GPSReading | None,
    ) -> bool:
        """Detect transition from riding to stopped/walking."""
        if activity in (ActivityType.STILL.value, ActivityType.WALKING.value):
            return True
        return False

    def _is_returning(
        self,
        activity: str,
        confidence: float,
        vehicle_hint: str,
        gps: GPSReading | None,
        session: SessionState,
    ) -> bool:
        """Detect return to vehicle within TTL and parking radius."""
        if not self._is_verified_vehicle(activity, confidence, vehicle_hint):
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

    def _is_verified_vehicle(
        self,
        activity: str,
        confidence: float,
        vehicle_hint: str,
        threshold: float = VEHICLE_HIGH_CONFIDENCE_THRESHOLD,
    ) -> bool:
        if activity != ActivityType.IN_VEHICLE.value or confidence < threshold:
            return False
        try:
            vehicle = VehicleClass(vehicle_hint)
        except ValueError:
            return False
        return vehicle not in (VehicleClass.UNKNOWN, VehicleClass.NOT_VEHICLE)

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
