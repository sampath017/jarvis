"""
Commands Router — POST /commands.

Handles user text commands, passes them to Tier 2, executes allowed tool actions,
and returns structured responses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, cast
from fastapi import APIRouter, Depends, status

from langgraph.graph.state import CompiledStateGraph  # type: ignore[import-untyped]

from ...graph.state import JarvisState
from ...models.schemas import APIResponse, CommandRequest
from ...services.firestore_service import FirestoreService
from ..auth import get_current_user
from ..dependencies import get_workflow
from ..rate_limiter import TokenBudgetGuard

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
    Process an explicit user text/voice command with TokenBudgetGuard protection.
    """
    guard = TokenBudgetGuard()
    guard.check_request_rate(uid)

    # Deduplication cache: check if identical command was processed recently
    cache_key = guard.compute_cache_key("cmd", f"{uid}:{request.thread_id}:{request.text}")
    cached_response = guard.get_cached_response(cache_key)
    if cached_response is not None:
        logger.info("Returning cached deduplicated command response for user %s", uid)
        return cast(APIResponse, cached_response)

    # Reserve estimated tokens before calling LLM
    estimated_tokens = len(request.text) // 3 + 250
    guard.check_and_reserve_tokens(uid, estimated_tokens)

    import time
    start_time = time.perf_counter()
    logger.info(
        "💬 [CHAT_START] Request ID: %s | User: %s | Thread: %s | Query: \"%s\"",
        request.request_id,
        uid,
        request.thread_id,
        request.text,
    )

    gps_dict = None
    if request.latitude is not None and request.longitude is not None:
        gps_dict = {
            "latitude": request.latitude,
            "longitude": request.longitude,
            "accuracy_m": 10.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from ...services.database import DatabaseService
            db = DatabaseService()
            db.create_event(
                uid,
                {
                    "activity": "USER_INTERACTION",
                    "transition": "COMMAND",
                    "gps": gps_dict,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as ge:
            logger.debug("Optional GPS context recording skipped: %s", ge)

    initial_state: dict[str, object] = {
        "uid": uid,
        "thread_id": request.thread_id,
        "request_type": "USER_COMMAND",
        "raw_request": request.model_dump(mode="json"),
        "context_packet": {"gps": gps_dict} if gps_dict else {},
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

        response = APIResponse(
            run_id=result.get("run_id", ""),
            status=status_str,
            message=response_msg,
            changed_records=result.get("changed_records", []),
            session_id=result.get("session_id"),
            error=error_msg,
            intent=result.get("intent"),
            resolved_place=result.get("resolved_place"),
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if status_str == "ok":
            guard.record_llm_usage(uid, prompt_tokens=estimated_tokens, completion_tokens=80)
            guard.store_cached_response(cache_key, response)

            # Persist chat turn and session directly to Firestore
            try:
                fs = FirestoreService()
                if fs.is_available:
                    thread = request.thread_id or "default"
                    # User message
                    fs.save_chat_message(
                        uid=uid,
                        thread_id=thread,
                        message={
                            "id": request.request_id,
                            "role": "user",
                            "content": request.text,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    # Assistant reply
                    fs.save_chat_message(
                        uid=uid,
                        thread_id=thread,
                        message={
                            "id": response.run_id or f"resp-{request.request_id}",
                            "role": "assistant",
                            "content": response.message,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "run_id": response.run_id,
                            "executed_records": response.changed_records,
                            "intent": response.intent,
                            "resolved_place": response.resolved_place,
                        },
                    )
                    # Session update
                    fs.save_chat_session(
                        session_id=thread,
                        data={
                            "id": thread,
                            "uid": uid,
                            "title": request.text[:35] + ("..." if len(request.text) > 35 else ""),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            except Exception as fe:
                logger.warning("Failed to auto-save chat turn to Firestore: %s", fe)

            logger.info(
                "✅ [CHAT_SUCCESS] Request ID: %s | Latency: %.1f ms | Executed Actions: %s | Response: \"%s\"",
                request.request_id,
                elapsed_ms,
                response.changed_records,
                response.message,
            )
        else:
            logger.warning(
                "⚠️ [CHAT_WARNING] Request ID: %s | Latency: %.1f ms | Error: %s",
                request.request_id,
                elapsed_ms,
                error_msg,
            )

        return response


    except Exception as e:  # pylint: disable=broad-exception-caught
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error(
            "❌ [CHAT_FAILED] Request ID: %s | Latency: %.1f ms | Error: %s",
            request.request_id,
            elapsed_ms,
            e,
        )
        return APIResponse(
            status="error",
            message="Internal workflow execution error",
            error=str(e),
        )


@router.delete("/chat-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session_endpoint(
    session_id: str,
    uid: Annotated[str, Depends(get_current_user)],
) -> None:
    """Delete a chat session and all its messages from Firestore."""
    fs = FirestoreService()
    if fs.is_available:
        fs.delete_chat_session(session_id)
    return None


@router.delete("/chat-sessions", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_chat_sessions_endpoint(
    uid: Annotated[str, Depends(get_current_user)],
) -> None:
    """Delete all chat sessions and messages for the user from Firestore."""
    fs = FirestoreService()
    if fs.is_available:
        fs.delete_all_chat_sessions(uid)
    return None
