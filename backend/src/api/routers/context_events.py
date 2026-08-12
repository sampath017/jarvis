"""
Context Events Router — POST /context-events.

Handles activity transitions, sensor features, and locations from Android client.
"""

from __future__ import annotations

import logging
from typing import Annotated
from fastapi import APIRouter, Depends, status

from langgraph.graph.state import CompiledStateGraph

from ...graph.state import JarvisState
from ...models.schemas import APIResponse, ContextEventRequest
from ...backend.context_automation import ContextAutomationService
from ..auth import get_current_user
from ..dependencies import get_workflow

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

    Triggers the LangGraph workflow to update the session state machine and resolve
    contextual conflicts.
    """
    logger.info("Received context event: event_id=%s uid=%s",
                request.event_id, uid)

    initial_state = {
        "uid": uid,
        "request_type": "CONTEXT_EVENT",
        "raw_request": request.model_dump(mode="json"),
    }

    try:
        result = workflow.invoke(initial_state)

        # Context-triggered actions are deliberately deterministic and run only
        # after the event has been persisted. They create durable notification
        # outbox records that the Android client can fetch and display.
        automation_changes = ContextAutomationService().process_context_event(
            uid, request.model_dump(mode="json"),
        )

        status_str = "error" if result.get("error") else "ok"
        error_msg = result.get("error")

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
        logger.error("Failed to run context-event workflow: %s", e)
        return APIResponse(
            status="error",
            message="Internal workflow execution error",
            error=str(e),
        )
