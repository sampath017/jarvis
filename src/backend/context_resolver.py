"""
FR-08: Conflict Resolution & Tier 1 Invocation Logic

Determines whether the deterministic context is clear or ambiguous,
and decides when to invoke the Tier 1 reasoner.
"""

from __future__ import annotations

from ..config import CONFLICT_CONFIDENCE_THRESHOLD, GPS_ACCURACY_POOR_M
from ..models.enums import ActivityType
from ..models.schemas import (
    ClassificationResult,
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

    def detect_conflicts(
        self, packet: ContextPacket, session: SessionState | None
    ) -> list[str]:
        """
        Detect all conflict conditions that warrant Tier 1 invocation.

        Triggers (from BRD):
        - GPS data conflicts with IMU classification
        - GPS accuracy is poor or drifting
        - Device reports IN_VEHICLE but fingerprint is weak
        - User visits a new or ambiguous POI
        - Multiple nearby businesses could represent destination
        - Must determine: parked, stopped at traffic, or ended journey
        - Session-continuity state machine produces ambiguous result
        """
        conflicts: list[str] = []

        classification = packet.classification
        activity = packet.activity_transition
        gps = packet.gps
        pois = packet.nearby_pois

        # 1. GPS accuracy is poor
        if gps and gps.accuracy_m > GPS_ACCURACY_POOR_M:
            conflicts.append(
                f"GPS accuracy poor: {gps.accuracy_m:.1f}m > {GPS_ACCURACY_POOR_M}m threshold"
            )

        # 2. IN_VEHICLE but weak fingerprint
        if (activity and activity.activity == ActivityType.IN_VEHICLE
                and classification
                and classification.confidence < CONFLICT_CONFIDENCE_THRESHOLD):
            conflicts.append(
                f"IN_VEHICLE with weak fingerprint: confidence={classification.confidence:.2f} "
                f"< threshold={CONFLICT_CONFIDENCE_THRESHOLD}"
            )

        # 3. GPS vs classification conflict
        if gps and classification and activity:
            if (activity.activity == ActivityType.IN_VEHICLE
                    and gps.speed_mps < 1.0
                    and classification.confidence > 0.5):
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

        # 6. Session ambiguity — paused but unclear if parked vs traffic vs ended
        if (session and session.status.value == "PAUSED"
                and classification
                and classification.confidence < CONFLICT_CONFIDENCE_THRESHOLD):
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
            classification_confidence=(
                packet.classification.confidence if packet.classification else 0.0
            ),
            gps_accuracy_m=packet.gps.accuracy_m if packet.gps else 0.0,
        )
