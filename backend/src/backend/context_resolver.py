"""
Conflict Resolution & Tier 1 Invocation Logic

Determines whether the deterministic context is clear or ambiguous,
and decides when to invoke the Tier 1 reasoner.
"""

from __future__ import annotations

from ..settings import GPS_ACCURACY_POOR_M, VEHICLE_HIGH_CONFIDENCE_THRESHOLD
from ..models.enums import ActivityType, VehicleClass
from ..models.schemas import (
    ContextPacket,
    SessionState,
    Tier1Request,
)


class ContextResolver:
    """
    Evaluates context packets for conflicts and ambiguity.
    Invokes Tier 1 only when deterministic resolution is insufficient.
    """

    def needs_tier1(self, packet: ContextPacket, session: SessionState | None) -> bool:
        """Check if this context packet has unresolvable ambiguity."""
        reasons = self.detect_conflicts(packet, session)
        return len(reasons) > 0

    def is_verified_vehicle(self, packet: ContextPacket) -> bool:
        """Whether the raw burst alone is safe to send to the state machine."""
        if packet.feature_summary is None:
            return False
        try:
            vehicle = VehicleClass(packet.vehicle_class_hint)
        except ValueError:
            return False
        return (
            vehicle not in (VehicleClass.UNKNOWN, VehicleClass.NOT_VEHICLE)
            and packet.classification_confidence >= VEHICLE_HIGH_CONFIDENCE_THRESHOLD
        )

    def detect_conflicts(
        self, packet: ContextPacket, session: SessionState | None,
    ) -> list[str]:
        """
        Detect all conflict conditions that warrant Tier 1 invocation.

        Triggers:
        - GPS accuracy is poor or drifting
        - Device reports IN_VEHICLE but fingerprint confidence is weak
        - GPS vs classification conflict (stationary but vehicle detected)
        - Multiple nearby businesses could represent destination
        - Unknown/ambiguous POI
        - Session paused with unclear context
        """
        conflicts: list[str] = []

        gps = packet.gps
        activity = packet.activity
        confidence = packet.classification_confidence
        pois = packet.nearby_pois

        # 1. GPS accuracy is poor
        if gps and gps.accuracy_m > GPS_ACCURACY_POOR_M:
            conflicts.append(
                f"GPS accuracy poor: {gps.accuracy_m:.1f}m > {GPS_ACCURACY_POOR_M}m threshold"
            )

        # 2. An IN_VEHICLE transition with a burst that is not a verified
        # vehicle is ambiguous. NOT_VEHICLE is a definitive negative result,
        # so it bypasses Tier 1 and cannot create a session.
        if (
            activity == ActivityType.IN_VEHICLE.value
            and packet.feature_summary is not None
            and packet.vehicle_class_hint != VehicleClass.NOT_VEHICLE.value
            and not self.is_verified_vehicle(packet)
        ):
            conflicts.append(
                f"IN_VEHICLE with low or ambiguous fingerprint: "
                f"confidence={confidence:.2f} < threshold={VEHICLE_HIGH_CONFIDENCE_THRESHOLD}"
            )

        # 3. GPS vs classification conflict
        if gps and activity == ActivityType.IN_VEHICLE.value:
            if gps.speed_mps is not None and gps.speed_mps < 1.0 and self.is_verified_vehicle(packet):
                conflicts.append(
                    "GPS shows stationary but classification indicates vehicle motion"
                )

        # 4. Multiple ambiguous POIs
        if len(pois) > 1:
            high_confidence_pois = [p for p in pois if p.confidence > 0.5]
            if len(high_confidence_pois) > 1:
                conflicts.append(
                    f"Multiple candidate POIs with high confidence: "
                    f"{[p.name for p in high_confidence_pois]}"
                )

        # 5. Unknown/ambiguous POI
        if pois:
            unknown_pois = [p for p in pois if p.category == "unknown"]
            if unknown_pois:
                conflicts.append(
                    f"Unknown POI category: {[p.name for p in unknown_pois]}"
                )

        # 6. Session ambiguity
        if (
            session
            and session.status.value == "PAUSED"
            and not self.is_verified_vehicle(packet)
        ):
            conflicts.append(
                "Session paused with ambiguous context: "
                "cannot determine if parked, traffic stop, or journey end"
            )

        return conflicts

    def build_tier1_request(
        self,
        packet: ContextPacket,
        session: SessionState | None,
        conflicts: list[str],
    ) -> Tier1Request:
        """Package a Tier 1 request from the context packet and detected conflicts."""
        return Tier1Request(
            event_id=packet.event_id,
            context_packet=packet,
            session=session,
            conflict_reason="; ".join(conflicts),
            classification_confidence=packet.classification_confidence,
            gps_accuracy_m=packet.gps.accuracy_m if packet.gps else 0.0,
        )
