"""HTTP client transport and simulation runners."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.models import ActivityEvent, ChatTurn, HttpResult


def post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    correlation_id: str,
    timeout_seconds: float,
) -> HttpResult:
    """POST one API payload using only the Python standard library."""
    request = Request(
        url=f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 -- target supplied by local developer
            return HttpResult(response.status, _decode_json(response.read()))
    except HTTPError as error:
        return HttpResult(error.code, _decode_json(error.read()), error=f"HTTP {error.code}")
    except URLError as error:
        return HttpResult(None, "", error=f"Network error: {error.reason}")


def post_context_event(
    base_url: str,
    payload: dict[str, Any],
    correlation_id: str,
    timeout_seconds: float,
) -> HttpResult:
    return post_json(base_url, "/context-events", payload, correlation_id, timeout_seconds)


def _decode_json(raw: bytes) -> dict[str, Any] | str:
    text = raw.decode("utf-8", errors="replace")
    try:
        decoded = json.loads(text)
        return decoded if isinstance(decoded, dict) else text
    except json.JSONDecodeError:
        return text


def run_scenario(
    events: Iterable[ActivityEvent],
    *,
    base_url: str,
    dry_run: bool,
    delay_seconds: float,
    timeout_seconds: float,
) -> int:
    """Submit one context-event scenario and print results."""
    anchor = datetime.now(UTC)
    correlation_id = str(uuid.uuid4())
    failures = 0

    for sequence, event in enumerate(events, start=1):
        payload = event.to_payload(anchor, sequence)
        if dry_run:
            print(
                json.dumps(
                    {
                        "offset_min": event.offset.total_seconds() / 60,
                        "note": event.note,
                        "payload": payload,
                    },
                    indent=2,
                )
            )
            continue

        result = post_context_event(base_url, payload, correlation_id, timeout_seconds)
        status = "OK" if result.successful else "FAILED"
        session_id = result.body.get("session_id") if isinstance(result.body, dict) else None
        message = result.body.get("message", "") if isinstance(result.body, dict) else str(result.body)
        print(
            f"[{sequence:02d}] {status:6} {event.activity:12} "
            f"HTTP {result.status_code or '-':>3}  session={session_id or '-'}  {message or result.error or ''}"
        )
        if not result.successful:
            failures += 1
            if result.error:
                print(f"     {result.error}")
        if delay_seconds:
            time.sleep(delay_seconds)

    if dry_run:
        print(f"\nDry run complete: {sequence} events generated successfully (no HTTP requests sent).")
    else:
        print(f"\nScenario complete: {failures} failed request(s).")
    return 1 if failures else 0


def run_chat_and_context_script(
    steps: Iterable[ActivityEvent | ChatTurn],
    *,
    base_url: str,
    dry_run: bool,
    delay_seconds: float,
    timeout_seconds: float,
) -> int:
    """Run an interleaved chat + context event workload through both endpoints."""
    anchor = datetime.now(UTC)
    correlation_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    failures = 0
    event_sequence = 0
    chat_sequence = 0
    latest_context_ref: str | None = None
    effective_delay = max(delay_seconds, 2.1) if not dry_run else 0.0

    for step_number, step in enumerate(steps, start=1):
        if isinstance(step, ActivityEvent):
            event_sequence += 1
            payload = step.to_payload(anchor, event_sequence)
            latest_context_ref = payload["event_id"]
            kind = f"CONTEXT {step.activity}"
            message = step.note
            path = "/context-events"
        else:
            chat_sequence += 1
            payload = {
                "request_id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "text": step.text,
                "current_context_ref": latest_context_ref,
            }
            kind = "CHAT"
            message = step.note
            path = "/commands"

        if dry_run:
            print(json.dumps({"step": step_number, "kind": kind, "note": message, "payload": payload}, indent=2))
            continue

        result = post_json(base_url, path, payload, correlation_id, timeout_seconds)
        status = "OK" if result.successful else "FAILED"
        response_message = result.body.get("message", "") if isinstance(result.body, dict) else str(result.body)
        changed = result.body.get("changed_records", []) if isinstance(result.body, dict) else []
        print(f"[{step_number:02d}] {status:6} {kind:18} changed={len(changed):2}  {response_message[:120]}")
        if not result.successful:
            failures += 1
            if result.error:
                print(f"     {result.error}")
        if effective_delay:
            time.sleep(effective_delay)

    if dry_run:
        print(f"\nDry run complete: {chat_sequence} chats and {event_sequence} context events (no HTTP requests sent).")
    else:
        print(f"\nSimulation complete: {chat_sequence} chats, {event_sequence} context events, {failures} failed request(s).")
    return 1 if failures else 0
