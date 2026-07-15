"""
End-to-End Pipeline Orchestrator

Connects all stages of the Jarvis system:
1. Activity transition → IMU burst capture
2. Feature extraction → Vehicle classification
3. Context packet assembly
4. Session state machine update
5. Conflict detection → conditional Tier 1 invocation
6. Optional user command → Tier 2 invocation
7. Function call validation → CRUD execution
8. Audit logging at every step
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .backend.audit_log import AuditLog
from .backend.context_resolver import ContextResolver
from .backend.crud_store import CRUDStore
from .backend.session_manager import SessionManager
from .cloud.function_registry import FunctionRegistry
from .cloud.tier1_reasoner import Tier1Reasoner
from .cloud.tier2_orchestrator import Tier2Orchestrator
from .edge.feature_extractor import extract_features
from .edge.imu_sampler import generate_imu_burst
from .edge.vehicle_classifier import classify_vehicle
from .models.enums import ActivityType, VehicleClass
from .models.schemas import (
    ActivityTransition,
    ClassificationResult,
    ContextPacket,
    GPSReading,
    PipelineResult,
    POICandidate,
    SessionState,
    Tier2Request,
)


class JarvisPipeline:
    """
    End-to-end Jarvis pipeline orchestrator.

    Processes events from activity transition through to CRUD execution,
    with full audit logging at every decision point.
    """

    def __init__(self, use_mock_llm: bool = True) -> None:
        self.session_manager = SessionManager()
        self.context_resolver = ContextResolver()
        self.crud_store = CRUDStore()
        self.function_registry = FunctionRegistry(self.crud_store)
        self.tier1 = Tier1Reasoner(use_mock=use_mock_llm)
        self.tier2 = Tier2Orchestrator(self.function_registry, use_mock=use_mock_llm)
        self.audit = AuditLog()

    def process_event(
        self,
        vehicle_type: VehicleClass,
        activity: ActivityTransition,
        gps: GPSReading | None = None,
        nearby_pois: list[POICandidate] | None = None,
        user_command: str | None = None,
        imu_seed: int | None = None,
        skip_imu: bool = False,
    ) -> PipelineResult:
        """
        Run a single event through the complete Jarvis pipeline.

        Args:
            vehicle_type: The actual vehicle/activity for IMU generation
            activity: The activity transition event from Android
            gps: GPS reading (optional)
            nearby_pois: POI candidates near the user (optional)
            user_command: User text command for Tier 2 processing (optional)
            imu_seed: Random seed for reproducible IMU generation
            skip_imu: If True, skip IMU sampling (e.g., for walking-only events)
        """
        pipeline_start = time.perf_counter()
        result = PipelineResult()

        # ── Stage 1: Activity Transition (OS trigger) ────────────────────
        self.audit.log(
            event_id="",
            component="activity_recognition",
            action=f"Transition: {activity.activity.value} ({activity.transition.value})",
            input_ref={"activity": activity.activity.value,
                       "transition": activity.transition.value},
            output={},
            execution_result="success",
        )

        classification = None

        if not skip_imu and activity.activity in (
            ActivityType.IN_VEHICLE, ActivityType.ON_BICYCLE
        ):
            # ── Stage 2: IMU Burst Capture ───────────────────────────────
            burst = generate_imu_burst(vehicle_type, seed=imu_seed)
            self.audit.log(
                event_id="",
                component="imu_sampler",
                action=f"Captured {burst.num_samples} samples at {burst.sampling_rate_hz}Hz",
                input_ref={"vehicle_type": vehicle_type.value,
                           "duration": burst.duration_sec},
                output={"num_samples": burst.num_samples},
                execution_result="success",
            )

            # ── Stage 3: Feature Extraction ──────────────────────────────
            features = extract_features(burst)
            self.audit.log(
                event_id="",
                component="feature_extractor",
                action="Extracted time-domain and frequency-domain features",
                input_ref={"num_samples": burst.num_samples},
                output={
                    "dominant_freq": features.accel_freq.dominant_freq_hz,
                    "spectral_energy": features.accel_freq.spectral_energy,
                    "z_rms": features.accel_z_features.rms,
                    "harmonic_ratio": features.accel_freq.harmonic_ratio,
                },
                execution_result="success",
            )

            # ── Stage 4: Vehicle Classification ─────────────────────────
            classification = classify_vehicle(features)
            self.audit.log(
                event_id="",
                component="classifier",
                action=f"Classified as {classification.vehicle_class.value}",
                input_ref={"dominant_freq": features.accel_freq.dominant_freq_hz},
                output={
                    "vehicle_class": classification.vehicle_class.value,
                    "confidence": classification.confidence,
                    "is_match": classification.is_match,
                },
                confidence=classification.confidence,
                execution_result="success",
            )
        else:
            features = None

        # ── Stage 5: Context Packet Assembly ─────────────────────────────
        packet = ContextPacket(
            timestamp=activity.timestamp,
            activity_transition=activity,
            gps=gps,
            features=features,
            classification=classification,
            nearby_pois=nearby_pois or [],
        )
        result.event_id = packet.event_id
        result.context_packet = packet
        result.classification = classification

        # Update event_id in audit entries
        for entry in self.audit.entries:
            if not entry.event_id:
                entry.event_id = packet.event_id

        # ── Stage 6: Session State Machine ───────────────────────────────
        session = self.session_manager.process_event(packet)
        if session:
            packet.session_id = session.session_id
            self.audit.log(
                event_id=packet.event_id,
                component="session_manager",
                action=f"Session {session.status.value}",
                input_ref={"session_id": session.session_id},
                output={
                    "status": session.status.value,
                    "vehicle": session.vehicle_class.value,
                    "resume_count": session.resume_count,
                },
                execution_result="success",
            )
        result.session = session

        # ── Stage 7: Conflict Detection → Tier 1 ────────────────────────
        tier1_response = None
        conflicts = self.context_resolver.detect_conflicts(packet, session)

        if conflicts:
            result.tier1_invoked = True
            tier1_request = self.context_resolver.build_tier1_request(
                packet, session, conflicts
            )
            tier1_response = self.tier1.resolve(tier1_request)
            result.tier1_response = tier1_response

            self.audit.log(
                event_id=packet.event_id,
                component="tier1_reasoner",
                action=f"Resolved: {tier1_response.recommended_action.value}",
                input_ref={"conflicts": conflicts},
                output={
                    "resolved_vehicle": tier1_response.resolved_vehicle.value,
                    "resolved_place": tier1_response.resolved_place,
                    "action": tier1_response.recommended_action.value,
                    "confidence": tier1_response.confidence,
                },
                confidence=tier1_response.confidence,
                model_id=tier1_response.model_id,
                execution_result="success",
            )

            # Apply Tier 1 recommendation to session
            if session and tier1_response.recommended_action.value == "COMPLETE":
                self.session_manager.force_complete(session.session_id)
                session = self.session_manager.get_session(session.session_id)
                result.session = session

        # ── Stage 8: User Command → Tier 2 ──────────────────────────────
        if user_command:
            result.tier2_invoked = True

            resolved_place = ""
            resolved_category = ""
            if tier1_response and tier1_response.resolved_place:
                resolved_place = tier1_response.resolved_place
                resolved_category = tier1_response.place_category
            elif nearby_pois:
                best = max(nearby_pois, key=lambda p: p.confidence)
                resolved_place = best.name
                resolved_category = best.category

            tier2_request = Tier2Request(
                user_command=user_command,
                context_packet=packet,
                session=session,
                tier1_response=tier1_response,
                resolved_place=resolved_place,
                resolved_place_category=resolved_category,
            )

            tier2_response = self.tier2.process_command(tier2_request)
            result.tier2_response = tier2_response

            self.audit.log(
                event_id=packet.event_id,
                component="tier2_orchestrator",
                action=f"Processed: '{user_command[:50]}'",
                input_ref={"command": user_command, "place": resolved_place},
                output={
                    "user_response": tier2_response.user_response[:100],
                    "num_calls": len(tier2_response.function_calls),
                    "all_valid": tier2_response.all_calls_valid,
                },
                model_id=tier2_response.model_id,
                execution_result="success",
            )

            # ── Stage 9: Execute Valid Function Calls ────────────────────
            for call in tier2_response.function_calls:
                if call.is_valid:
                    exec_result = self.function_registry.execute(call)
                    self.audit.log(
                        event_id=packet.event_id,
                        component="function_registry",
                        action=f"Executed: {call.function_name}",
                        input_ref={"function": call.function_name,
                                   "args": call.arguments},
                        output=exec_result,
                        execution_result="success" if exec_result.get("success") else "error",
                    )
                else:
                    self.audit.log(
                        event_id=packet.event_id,
                        component="function_registry",
                        action=f"REJECTED: {call.function_name}",
                        input_ref={"function": call.function_name},
                        output={},
                        execution_result="rejected",
                        error_detail=call.validation_error,
                    )

        # ── Finalize ─────────────────────────────────────────────────────
        elapsed_ms = (time.perf_counter() - pipeline_start) * 1000
        result.total_latency_ms = round(elapsed_ms, 2)
        result.audit_entries = self.audit.get_entries_for_event(packet.event_id)

        return result

    def reset(self) -> None:
        """Reset all state for a fresh scenario run."""
        self.session_manager = SessionManager()
        self.crud_store.clear()
        self.audit.clear()
