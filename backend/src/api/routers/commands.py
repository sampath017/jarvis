"""
Commands Router — POST /commands.

Handles user text commands, passes them to Tier 2, executes allowed tool actions,
and returns structured responses.
"""

from __future__ import annotations

import logging
import asyncio
import json
import time
import os
from datetime import datetime, timezone
from typing import Annotated, cast
from fastapi import APIRouter, Depends, status, Header, HTTPException
from fastapi.responses import StreamingResponse
from ...backend.command_execution import CommandExecution, execution, MAX_COMMAND_ROUNDS
from ...services.command_run_store import CommandRunStore
from ...services.background_tasks import BackgroundTasks, verify_task_identity
from ...services.push_notifications import PushNotifications

from langgraph.graph.state import CompiledStateGraph  # type: ignore[import-untyped]

from ...graph.state import JarvisState
from ...models.schemas import APIResponse, CommandRequest
from ...services.record_store import RecordStore
from ..auth import get_current_user
from ..dependencies import get_workflow
from ..rate_limiter import TokenBudgetGuard

logger = logging.getLogger(__name__)
router = APIRouter(tags=["commands"])



def _execute_user_command(request: CommandRequest, uid: str, workflow) -> APIResponse:
    """
    Process an explicit user text/voice command with TokenBudgetGuard protection.
    """
    guard = TokenBudgetGuard()
    guard.check_request_rate(uid)

    # Each actual model call reserves its full allowance at the call site.
    # Do not charge a second reservation for entering the command workflow.

    import time
    start_time = time.perf_counter()
    received_at = datetime.now(timezone.utc).isoformat()
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
        result = cast(JarvisState, workflow.invoke(initial_state, config={"recursion_limit": 2 * MAX_COMMAND_ROUNDS + 12}))

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
            needs_user_input=result.get("needs_user_input", False),
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if status_str == "ok":

            # Persist chat turn and session directly to RecordStore
            try:
                fs = RecordStore()
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
                            "timestamp": received_at,
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
                logger.warning("Failed to auto-save chat turn to RecordStore: %s", fe)

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
            error=str(getattr(e, "detail", e)),
            changed_records=list(execution.get().changed_records) if execution.get() else [],
        )


# Keep strong references so a network disconnect does not cancel an accepted run.
_running_tasks: set[asyncio.Task] = set()


def _run_owned(store, request, uid, workflow):
    accepted_at = store.get(uid, request.request_id)['started_at']
    queue_age = max(0, (datetime.now(timezone.utc) - accepted_at).total_seconds())
    context = CommandExecution(
        started=time.monotonic() - queue_age,
        publish=lambda message: store.progress(uid, request.request_id, message),
        cancelled=lambda: store.get(uid, request.request_id).get("cancel_requested", False),
    )
    if request.calendar_connected:
        context.calendar_dispatch = lambda action: store.calendar_action(uid, request.request_id,
            {**action, 'default_calendar_id': request.calendar_id}, context.check)
    if request.device_approvals:
        from ...services.device_context import dispatch_device_action
        context.approval_dispatch = lambda action: dispatch_device_action(uid, action,
            lambda: store.calendar_action(uid, request.request_id,
                {'operation': 'approval', **action}, context.check), context.check)
    # The accepted command stores only the hash of its private device capability.
    # Bind cloud execution to that same owner; never resolve a grant by fixed UID.
    from ...services.server_google_auth import ServerGoogleAuth, configured as cloud_google_configured
    cloud_auth = None
    cloud_executor = None
    owner = store.get(uid, request.request_id).get('calendar_key_hash')
    from ...services.mobile_scope import mobile_only
    if not mobile_only() and owner and cloud_google_configured() and owner == os.getenv('JARVIS_GOOGLE_OWNER_HASH'):
        cloud_auth = ServerGoogleAuth()
        if cloud_auth.status(owner).get('connected'):
            import hashlib
            from ...services.server_google_actions import ServerGoogleActions
            from ...services.scheduled_google_actions import ScheduledGoogleActions
            cloud_executor = ServerGoogleActions(owner, auth=cloud_auth)
            def action_id(action):
                return request.request_id + ':' + hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
            def cloud_dispatch(action):
                context.check()
                return cloud_executor.dispatch({**action, 'default_calendar_id': request.calendar_id}, action_id(action))
            context.server_google_dispatch = cloud_dispatch
            schedules = ScheduledGoogleActions(auth=cloud_auth)
            def schedule_dispatch(action):
                context.check()
                if action['operation'] == 'list':
                    return schedules.list(owner)
                if action['operation'] == 'cancel':
                    return schedules.cancel(owner, action['action_id'])
                saved_action = dict(action['action'])
                if saved_action.get('operation') in {'create', 'update', 'delete'}:
                    saved_action['calendar_id'] = saved_action.get('calendar_id') or request.calendar_id
                return schedules.create(owner, action_id(action), saved_action, action['execute_at'], action['title'], request.thread_id)
            context.schedule_dispatch = schedule_dispatch
    token = execution.set(context)
    try:
        try:
            response = _execute_user_command(request, uid, workflow).model_dump(mode="json")
        except Exception as error:
            response = {"status": "error", "error": str(getattr(error, "detail", error)),
                        "changed_records": list(context.changed_records)}
        if response.get('status') == 'error':
            fs = RecordStore()
            if fs.is_available:
                fs.save_chat_message(uid, request.thread_id, {
                    'id': 'err_' + request.request_id, 'role': 'assistant',
                    'content': response.get('error') or response.get('message') or 'Request stopped.',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'executed_records': response.get('changed_records', []),
                })
        store.finish(uid, request.request_id, response)
        try:
            from ...services.mobile_scope import mobile_only
            if not mobile_only():
                PushNotifications().queue_chat(uid, request.request_id, request.thread_id, response)
        except Exception:
            logger.exception('Chat push delivery deferred; response is saved')
    finally:
        execution.reset(token)
        if cloud_executor:
            cloud_executor.client.close()
        if cloud_auth:
            cloud_auth.client.close()


async def _start_run(request, uid, workflow, calendar_key=None):
    import os
    dispatcher = BackgroundTasks()
    store = CommandRunStore()
    if request.calendar_connected or request.device_approvals:
        if not calendar_key or not 64 <= len(calendar_key) <= 128:
            raise HTTPException(422, 'A private device session is required for Google Calendar.')
        fresh = await asyncio.to_thread(store.claim, uid, request, calendar_key)
    else:
        fresh = await asyncio.to_thread(store.claim, uid, request)
    dispatcher = BackgroundTasks()
    if dispatcher.configured:
        snapshot = await asyncio.to_thread(store.get, uid, request.request_id)
        if snapshot['status'] == 'queued':
            await asyncio.to_thread(dispatcher.enqueue, 'command',
                {'uid': uid, 'request_id': request.request_id}, f'command:{uid}:{request.request_id}')
        return store
    if fresh:
        task = asyncio.create_task(asyncio.to_thread(_run_owned, store, request, uid, workflow))
        _running_tasks.add(task)
        def finished(done):
            _running_tasks.discard(done)
            if not done.cancelled() and done.exception():
                logger.error("Command worker could not save its result", exc_info=done.exception())
        task.add_done_callback(finished)
    return store


async def _command_events(store, uid, request_id):
    from ...services.command_updates import command_updates
    from contextlib import aclosing
    last_sequence = None
    last_emit = 0.0
    last_action_id = None
    async with aclosing(command_updates(store, uid, request_id)) as updates:
        async for data in updates:
            snapshot = store.public(data)
            if snapshot['status'] == 'complete':
                yield 'event: result\ndata: ' + json.dumps(snapshot['response']) + '\n\n'
                return
            if data.get('calendar_action') and data.get('calendar_result') is None and not data.get('cancel_requested') and data['calendar_action']['action_id'] != last_action_id:
                yield 'event: calendar_action\ndata: ' + json.dumps(data['calendar_action']) + '\n\n'
                last_action_id = data['calendar_action']['action_id']
            sequence = (snapshot['sequence'], snapshot['message'])
            if sequence != last_sequence or time.monotonic() - last_emit >= 10:
                yield 'event: progress\ndata: ' + json.dumps(snapshot) + '\n\n'
                last_sequence, last_emit = sequence, time.monotonic()


@router.post('/commands/stream')
async def stream_user_command(
    request: CommandRequest,
    uid: Annotated[str, Depends(get_current_user)],
    workflow: Annotated[CompiledStateGraph, Depends(get_workflow)],
    x_calendar_session: Annotated[str | None, Header()] = None,
):
    store = await _start_run(request, uid, workflow, x_calendar_session)
    store.authorize(await asyncio.to_thread(store.get, uid, request.request_id), x_calendar_session)
    return StreamingResponse(_command_events(store, uid, request.request_id),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})


@router.post('/internal/background/command')
async def execute_background_command(payload: dict, authorization: Annotated[str | None, Header()] = None,
    workflow: CompiledStateGraph = Depends(get_workflow)):
    await asyncio.to_thread(verify_task_identity, authorization)
    store = CommandRunStore()
    uid, request_id = payload['uid'], payload['request_id']
    raw = await asyncio.to_thread(store.start_execution, uid, request_id)
    if raw is not None:
        await asyncio.to_thread(_run_owned, store, CommandRequest(**raw), uid, workflow)
    data = await asyncio.to_thread(store.get, uid, request_id)
    response = store.public(data).get('response')
    if response:
        await asyncio.to_thread(PushNotifications().queue_chat, uid, request_id, data.get('thread_id'), response)
    return {'status': 'ok'}


@router.post('/internal/background/reminder')
async def execute_due_reminder(payload: dict, authorization: Annotated[str | None, Header()] = None):
    await asyncio.to_thread(verify_task_identity, authorization)
    from ...backend.context_automation import ContextAutomationService
    def deliver_due():
        fs = RecordStore()
        reminder = fs._db.collection('reminders').document(payload['reminder_id']).get().to_dict()
        if reminder and reminder.get('uid') == payload['uid']:
            from ...services.database import DatabaseService
            db = DatabaseService()
            db.create_reminder(payload['uid'], reminder)
            BackgroundTasks().schedule_reminder(payload['uid'], reminder)
            ContextAutomationService(db=db, cloud=fs).process_due_reminders()
        PushNotifications().deliver(payload['uid'])
    await asyncio.to_thread(deliver_due)
    return {'status': 'ok'}


@router.post('/internal/background/notification')
async def deliver_background_notification(payload: dict, authorization: Annotated[str | None, Header()] = None):
    await asyncio.to_thread(verify_task_identity, authorization)
    await asyncio.to_thread(PushNotifications().deliver, payload['uid'])
    return {'status': 'ok'}


@router.post('/internal/background/activity-reminder')
async def deliver_activity_reminder(payload: dict, authorization: Annotated[str | None, Header()] = None):
    await asyncio.to_thread(verify_task_identity, authorization)
    def deliver():
        from ...services.activity_reminder_timers import ActivityReminderTimers
        from ...backend.context_automation import ContextAutomationService
        fs = RecordStore()
        ActivityReminderTimers(fs).deliver(payload['uid'], payload['reminder_id'], payload['timer_id'],
                                          ContextAutomationService(cloud=fs))
        PushNotifications().deliver(payload['uid'])
    await asyncio.to_thread(deliver)
    return {'status': 'ok'}


@router.get('/commands/requests/{request_id}')
async def command_status(request_id: str, uid: Annotated[str, Depends(get_current_user)], x_calendar_session: Annotated[str | None, Header()] = None):
    store = CommandRunStore()
    data = await asyncio.to_thread(store.get, uid, request_id)
    store.authorize(data, x_calendar_session)
    snapshot = store.public(data)
    if data.get('calendar_action') and data.get('calendar_result') is None and not data.get('cancel_requested'):
        snapshot['calendar_action'] = data['calendar_action']
    return snapshot


@router.post('/commands/requests/{request_id}/calendar-result')
async def calendar_result(request_id: str, payload: dict, uid: Annotated[str, Depends(get_current_user)], x_calendar_session: Annotated[str | None, Header()] = None):
    if not isinstance(payload.get('result'), dict) or len(json.dumps(payload)) > 8 * 1024 * 1024:
        raise HTTPException(422, 'Invalid calendar result')
    store = CommandRunStore()
    await asyncio.to_thread(store.calendar_result, uid, request_id, payload.get('action_id'), payload['result'], x_calendar_session)
    return {'status': 'ok'}


@router.post('/commands/requests/{request_id}/cancel')
async def cancel_command(request_id: str, uid: Annotated[str, Depends(get_current_user)], x_calendar_session: Annotated[str | None, Header()] = None):
    store = CommandRunStore()
    store.authorize(await asyncio.to_thread(store.get, uid, request_id), x_calendar_session)
    await asyncio.to_thread(store.cancel, uid, request_id)
    return {'status': 'stopping'}


@router.post('/commands', response_model=APIResponse)
async def process_user_command(
    request: CommandRequest,
    uid: Annotated[str, Depends(get_current_user)],
    workflow: Annotated[CompiledStateGraph, Depends(get_workflow)],
    x_calendar_session: Annotated[str | None, Header()] = None,
) -> APIResponse:
    # Compatibility for older clients, with the same durable request identity.
    store = await _start_run(request, uid, workflow, x_calendar_session)
    store.authorize(await asyncio.to_thread(store.get, uid, request.request_id), x_calendar_session)
    while True:
        snapshot = store.public(await asyncio.to_thread(store.get, uid, request.request_id))
        if snapshot['status'] == 'complete':
            return APIResponse(**snapshot['response'])
        await asyncio.sleep(1)


@router.delete("/chat-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session_endpoint(
    session_id: str,
    uid: Annotated[str, Depends(get_current_user)],
) -> None:
    """Delete a chat session and all its messages from RecordStore."""
    fs = RecordStore()
    if fs.is_available:
        fs.delete_chat_session(session_id)
    return None


@router.delete("/chat-sessions", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_chat_sessions_endpoint(
    uid: Annotated[str, Depends(get_current_user)],
) -> None:
    """Delete all chat sessions and messages for the user from RecordStore."""
    fs = RecordStore()
    if fs.is_available:
        fs.delete_all_chat_sessions(uid)
    return None
