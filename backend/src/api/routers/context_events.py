"""
Context Events Router — POST /v1/context-events.

Handles activity transitions, sensor features, and locations from Android client.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, status

from ...models.schemas import APIResponse, ContextEventRequest
from ..auth import get_current_user, verify_app_check
from ..dependencies import get_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["context-events"])


@router.post(
    "/context-events",
    response_model=APIResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_app_check)],
)
async def ingest_context_event(
    request: ContextEventRequest,
    uid: str = Depends(get_current_user),
    workflow=Depends(get_workflow),
):
    """
    Ingest a contextual event (activity transition, feature vector, location).

    Triggers the LangGraph workflow to update the session state machine and resolve
    contextual conflicts.
    """
    logger.info("Received context event: event_id=%s uid=%s", request.event_id, uid)

    # In Phase 1, each request runs a fresh graph invocation
    initial_state = {
        "uid": uid,
        "request_type": "CONTEXT_EVENT",
        "raw_request": request.model_dump(mode="json"),
    }

    try:
        # Run graph workflow synchronously for Phase 1
        result = workflow.invoke(initial_state)

        status_str = "error" if result.get("error") else "ok"
        error_msg = result.get("error")

        return APIResponse(
            run_id=result.get("run_id", ""),
            status=status_str,
            message="Event processed successfully" if status_str == "ok" else "Processing failed",
            changed_records=result.get("changed_records", []),
            session_id=result.get("session_id"),
            error=error_msg,
        )

    except Exception as e:
        logger.error("Failed to run context-event workflow: %s", e)
        return APIResponse(
            status="error",
            message="Internal workflow execution error",
            error=str(e),
        )
