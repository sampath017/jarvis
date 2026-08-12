"""
Commands Router — POST /commands.

Handles user text commands, passes them to Tier 2, executes allowed tool actions,
and returns structured responses.
"""

from __future__ import annotations

import logging
from typing import Annotated, cast
from fastapi import APIRouter, Depends, status

from langgraph.graph.state import CompiledStateGraph  # type: ignore[import-untyped]

from ...graph.state import JarvisState
from ...models.schemas import APIResponse, CommandRequest
from ..auth import get_current_user
from ..dependencies import get_workflow

logger = logging.getLogger(__name__)
router = APIRouter(tags=["commands"])


@router.post(
    "/commands",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
)
async def process_user_command(
    request: CommandRequest,
    uid: Annotated[str, Depends(get_current_user)],
    workflow: Annotated[CompiledStateGraph[JarvisState, None, JarvisState, JarvisState], Depends(get_workflow)],
) -> APIResponse:
    """
    Process an explicit user text/voice command.

    Triggers the LangGraph workflow: retrieves scoped memory context, invokes Tier 2,
    validates and executes allow-listed tools, and returns a concise user response.
    """
    logger.info("Received user command request_id=%s uid=%s",
                request.request_id, uid)

    initial_state: dict[str, object] = {
        "uid": uid,
        "request_type": "USER_COMMAND",
        "raw_request": request.model_dump(mode="json"),
    }

    try:
        # Run graph workflow synchronously
        result = cast(JarvisState, workflow.invoke(initial_state))

        status_str = "error" if result.get("error") else "ok"
        error_msg = result.get("error")

        # The message field carries the natural language response back to the user
        response_msg = (
            result.get("user_response", "")
            if status_str == "ok"
            else "Command processing failed"
        )

        return APIResponse(
            run_id=result.get("run_id", ""),
            status=status_str,
            message=response_msg,
            changed_records=result.get("changed_records", []),
            session_id=result.get("session_id"),
            error=error_msg,
        )

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to run command workflow: %s", e)
        return APIResponse(
            status="error",
            message="Internal workflow execution error",
            error=str(e),
        )
