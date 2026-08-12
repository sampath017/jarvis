"""Deterministic, local automation for reminders, notes, and notifications.

The mobile client remains responsible for showing an Android notification.  This
service creates a durable notification outbox record whenever a verified context
event meets a reminder or rule.  The client can poll and acknowledge that record
without giving an LLM direct access to device notification APIs.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from ..services.database import DatabaseService


class ContextAutomationService:
    """Evaluate local rules after a context event has been persisted."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()

    def process_context_event(self, uid: str, event: dict[str, Any]) -> list[str]:
        """Apply matching reminders and context rules, returning changed IDs."""
        occurred_at = _event_time(event)
        changed_ids: list[str] = []

        for reminder in self.db.list_reminders(uid, status="ACTIVE"):
            trigger = self._matching_reminder_trigger(uid, reminder, event, occurred_at)
            if not trigger:
                continue
            notification, created = self._fire_reminder(uid, reminder, event, occurred_at, trigger)
            if created:
                changed_ids.append(notification["id"])

        for rule in self.db.list_context_rules(uid, enabled=True):
            if not self._rule_matches(uid, rule, event, occurred_at):
                continue
            changed_ids.extend(self._execute_rule(uid, rule, event, occurred_at))

        return changed_ids

    def process_due_reminders(self, now: datetime | None = None) -> list[str]:
        """Queue overdue time reminders; call this from a scheduler or poll endpoint."""
        current = (now or datetime.now(UTC)).astimezone(UTC)
        changed_ids: list[str] = []
        for reminder in self.db.list_due_reminders(current.isoformat()):
            event = {"event_id": f"due:{reminder['id']}:{reminder['due_at']}", "occurred_at": current.isoformat()}
            notification, created = self._fire_reminder(uid=reminder["uid"], reminder=reminder, event=event, occurred_at=current, trigger="TIME_DUE")
            if created:
                changed_ids.append(notification["id"])
        return changed_ids

    def _matching_reminder_trigger(
        self, uid: str, reminder: dict[str, Any], event: dict[str, Any], occurred_at: datetime,
    ) -> str | None:
        event_id = str(event.get("event_id", ""))
        state = self.db.get_trigger_state(uid, "REMINDER", reminder["id"])
        if state and state.get("last_event_id") == event_id:
            return None

        has_location = reminder.get("latitude") is not None and reminder.get("longitude") is not None
        has_activity = bool(reminder.get("activity"))
        has_due = bool(reminder.get("due_at"))
        if not (has_location or has_activity or has_due):
            return None

        if has_location and not self._geofence_entered(uid, "REMINDER", reminder["id"], reminder, event, occurred_at):
            return None
        if has_activity and not _activity_entered(event, str(reminder["activity"])):
            return None
        if has_due and occurred_at < _parse_time(str(reminder["due_at"])):
            return None

        trigger_parts = []
        if has_location:
            trigger_parts.append("GEOFENCE_ENTER")
        if has_activity:
            trigger_parts.append("ACTIVITY_ENTER")
        if has_due:
            trigger_parts.append("TIME_DUE")
        # Keep geofence state intact so remaining inside the same radius does not
        # repeatedly fire a reminder. Activity-only reminders still record the
        # event for idempotency.
        if not has_location:
            self.db.upsert_trigger_state(uid, "REMINDER", reminder["id"], False, event_id, occurred_at.isoformat())
        return "+".join(trigger_parts)

    def _fire_reminder(
        self, uid: str, reminder: dict[str, Any], event: dict[str, Any], occurred_at: datetime,
        trigger: str,
    ) -> tuple[dict[str, Any], bool]:
        notification, created = self.db.create_notification(
            uid,
            {
                "reminder_id": reminder["id"],
                "title": reminder["title"],
                "body": reminder.get("body") or reminder["title"],
                "trigger_type": trigger,
                "event_id": str(event.get("event_id", "")),
                "payload": {
                    "reminder_id": reminder["id"],
                    "location_name": reminder.get("location_name"),
                    "occurred_at": occurred_at.isoformat(),
                },
            },
        )
        if created:
            patch: dict[str, Any] = {"last_fired_at": occurred_at.isoformat()}
            if reminder.get("one_shot", True):
                patch["status"] = "COMPLETED"
            self.db.update_reminder(uid, reminder["id"], patch)
        return notification, created

    def _rule_matches(
        self, uid: str, rule: dict[str, Any], event: dict[str, Any], occurred_at: datetime,
    ) -> bool:
        event_id = str(event.get("event_id", ""))
        state = self.db.get_trigger_state(uid, "CONTEXT_RULE", rule["id"])
        if state and state.get("last_event_id") == event_id:
            return False

        trigger_type = str(rule["trigger_type"]).upper()
        trigger = rule.get("trigger", {})
        if trigger_type == "GEOFENCE_ENTER":
            return self._geofence_entered(uid, "CONTEXT_RULE", rule["id"], trigger, event, occurred_at)
        if trigger_type == "ACTIVITY_ENTER":
            matched = _activity_entered(event, str(trigger.get("activity", "")))
            if matched:
                self.db.upsert_trigger_state(uid, "CONTEXT_RULE", rule["id"], False, event_id, occurred_at.isoformat())
            return matched
        if trigger_type == "TIME_AFTER":
            at = trigger.get("at")
            matched = bool(at) and occurred_at >= _parse_time(str(at))
            if matched:
                self.db.upsert_trigger_state(uid, "CONTEXT_RULE", rule["id"], False, event_id, occurred_at.isoformat())
            return matched
        return False

    def _geofence_entered(
        self, uid: str, source_type: str, source_id: str, trigger: dict[str, Any], event: dict[str, Any],
        occurred_at: datetime,
    ) -> bool:
        location = event.get("location") or event.get("gps") or {}
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        target_latitude = trigger.get("latitude")
        target_longitude = trigger.get("longitude")
        if None in (latitude, longitude, target_latitude, target_longitude):
            return False

        radius_m = float(trigger.get("radius_m", 100.0))
        inside = _haversine_m(float(latitude), float(longitude), float(target_latitude), float(target_longitude)) <= radius_m
        state = self.db.get_trigger_state(uid, source_type, source_id)
        previously_inside = bool(state and state.get("is_inside"))
        self.db.upsert_trigger_state(
            uid, source_type, source_id, inside, str(event.get("event_id", "")), occurred_at.isoformat(),
        )
        return inside and not previously_inside

    def _execute_rule(
        self, uid: str, rule: dict[str, Any], event: dict[str, Any], occurred_at: datetime,
    ) -> list[str]:
        action_type = str(rule["action_type"]).upper()
        action = rule.get("action", {})
        changed_ids: list[str] = []

        if action_type == "NOTIFY":
            notification, created = self.db.create_notification(
                uid,
                {
                    "context_rule_id": rule["id"],
                    "title": action.get("title", rule["name"]),
                    "body": action.get("body", ""),
                    "trigger_type": rule["trigger_type"],
                    "event_id": str(event.get("event_id", "")),
                    "payload": {"context_rule_id": rule["id"], "occurred_at": occurred_at.isoformat()},
                },
            )
            if created:
                changed_ids.append(notification["id"])

        elif action_type == "APPEND_NOTE":
            note_id = action.get("note_id")
            if not note_id and action.get("note_title"):
                matched_note = self.db.find_note_by_title(uid, str(action["note_title"]))
                note_id = matched_note["id"] if matched_note else None
            note = self.db.get_note(uid, note_id) if note_id else None
            if note:
                entry = str(action.get("text", "Context rule triggered"))
                content = note.get("content", "").rstrip()
                updated = self.db.update_note(
                    uid, note_id, {"content": f"{content}\n[{occurred_at.isoformat()}] {entry}".strip()},
                )
                if updated:
                    changed_ids.append(note_id)

        elif action_type == "UPDATE_REMINDER":
            reminder_id = action.get("reminder_id")
            if not reminder_id and action.get("reminder_title"):
                matched_reminder = self.db.find_reminder_by_title(uid, str(action["reminder_title"]))
                reminder_id = matched_reminder["id"] if matched_reminder else None
            patch = action.get("patch", {})
            if reminder_id and isinstance(patch, dict):
                updated = self.db.update_reminder(uid, reminder_id, patch)
                if updated:
                    changed_ids.append(reminder_id)

        if rule.get("one_shot", False):
            self.db.update_context_rule(
                uid, rule["id"], {"enabled": False, "last_fired_at": occurred_at.isoformat()},
            )
        else:
            self.db.update_context_rule(uid, rule["id"], {"last_fired_at": occurred_at.isoformat()})
        return changed_ids


def _event_time(event: dict[str, Any]) -> datetime:
    value = event.get("occurred_at") or event.get("timestamp") or datetime.now(UTC).isoformat()
    return _parse_time(str(value))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _activity_entered(event: dict[str, Any], expected: str) -> bool:
    return (
        str(event.get("transition", "ENTER")).upper() == "ENTER"
        and str(event.get("activity", "")).upper() == expected.upper()
    )


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
