"""
Context Events Router — POST /context-events.

Handles activity transitions, sensor features, and locations from Android client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, status

from langgraph.graph.state import CompiledStateGraph

from ...graph.state import JarvisState
from ...models.schemas import APIResponse, ContextEventRequest
from ...backend.context_automation import ContextAutomationService
from ..auth import get_current_user
from ..dependencies import get_workflow
from ..rate_limiter import TokenBudgetGuard

logger = logging.getLogger(__name__)
router = APIRouter(tags=["context-events"])


@router.post(
    "/context-events",
    response_model=APIResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_context_event(
    request: ContextEventRequest,
    uid: Annotated[str, Depends(get_current_user)],
    workflow: Annotated[CompiledStateGraph[JarvisState, None, JarvisState, JarvisState], Depends(get_workflow)],
) -> APIResponse:
    """
    Ingest a contextual event (activity transition, feature vector, location).
    Guarded by TokenBudgetGuard against rapid duplicate telemetry spikes.
    """
    TokenBudgetGuard().check_request_rate(uid)

    logger.info(
        "📡 [EVENT_START] Ingested context event | ID: %s | User: %s | Type: %s | Activity: %s",
        request.event_id,
        uid,
        request.event_type,
        request.activity,
    )
    if request.event_type == "SESSION_START":
        logger.info("🏍️ [SESSION_START] Riding journey initiated | Session: %s | User: %s", request.session_id, uid)
    elif request.event_type in ("SESSION_END", "SESSION_STOP"):
        logger.info("🏁 [SESSION_END] Riding journey concluded | Session: %s | User: %s", request.session_id, uid)

    initial_state = {
        "uid": uid,
        "request_type": "CONTEXT_EVENT",
        "raw_request": request.model_dump(mode="json"),
    }

    # Event types eligible for user-facing automation (reminder/notification eval).
    # Internal telemetry events (BOUNDED_IMU_BURST, TELEMETRY_PIPELINE_CHECK)
    # are excluded so that riding-burst data never surfaces as notifications.
    _AUTOMATION_ELIGIBLE_EVENTS = {
        "ACTIVITY_ENTER", "ACTIVITY_EXIT",
        "SESSION_START", "SESSION_END", "SESSION_STOP",
        "GEOFENCE_ENTER", "GEOFENCE_EXIT",
        "CONTEXT_CHECKPOINT", "DWELL_CHECK", "ACTIVITY_SAMPLE",
    }

    try:
        result = workflow.invoke(initial_state)

        # Context-triggered actions are deliberately deterministic and run only
        # after the event has been persisted. They create durable notification
        # outbox records that the Android client can fetch and display.
        # Only genuine activity transitions are eligible — internal telemetry
        # bursts (e.g. 10s IMU burst while riding) must not create notifications.
        event_data = request.model_dump(mode="json")
        event_data["semantic_contexts"] = result.get("semantic_contexts", [])
        event_type = str(event_data.get("event_type") or event_data.get("transition") or "").upper()
        observed = datetime.fromisoformat(str(event_data["occurred_at"]).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        fresh = 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 300
        if event_type in _AUTOMATION_ELIGIBLE_EVENTS and not result.get("error") and fresh:
            automation_changes = ContextAutomationService().process_context_event(
                uid, event_data,
            )
        else:
            automation_changes = []

        status_str = "error" if result.get("error") else "ok"
        error_msg = result.get("error")

        logger.info(
            "📡 [EVENT_PROCESSED] ID: %s | Status: %s | Triggered Actions: %s",
            request.event_id,
            status_str,
            automation_changes,
        )

        return APIResponse(
            run_id=result.get("run_id", ""),
            status=status_str,
            message="Event processed successfully" if status_str == "ok" else "Processing failed",
            changed_records=[
                *result.get("changed_records", []), *automation_changes],
            session_id=result.get("session_id"),
            error=error_msg,
        )

    except Exception as e:
        logger.exception("Failed to run context-event workflow: %s", e)
        return APIResponse(
            status="error",
            message="Internal workflow execution error",
            error=str(e),
        )
