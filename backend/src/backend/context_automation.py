"""Deterministic, local automation for reminders, notes, and notifications.

The mobile client remains responsible for showing an Android notification.  This
service creates a durable notification outbox record whenever a verified context
event meets a reminder or rule.  The client can poll and acknowledge that record
without giving an LLM direct access to device notification APIs.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime
from typing import Any

from ..services.database import DatabaseService
from ..settings import MIN_DWELL_SEC

logger = logging.getLogger(__name__)


class ContextAutomationService:
    """Evaluate local rules after a context event has been persisted."""

    def __init__(self, db: DatabaseService | None = None, cloud=None) -> None:
        self.db = db or DatabaseService()
        import sys
        from ..services.firestore_service import FirestoreService
        self.cloud = cloud
        if self.cloud is None and "pytest" not in sys.modules:
            service = FirestoreService()
            self.cloud = service if service.is_available else None

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
            # Context conditions are conjunctive, including when a timer expires.
            if reminder.get("activity") or reminder.get("location_name") or reminder.get("latitude") is not None:
                continue
            due_at_val = (reminder.get("due_at") or "").strip()
            if not due_at_val:
                continue
            event = {"event_id": f"due:{reminder['id']}:{due_at_val}", "occurred_at": current.isoformat()}
            notification, created = self._fire_reminder(uid=reminder["uid"], reminder=reminder, event=event, occurred_at=current, trigger="TIME_DUE")
            if created:
                changed_ids.append(notification["id"])
        # Recheck recent observations even when no new activity transition occurs.
        # Never extrapolate an old observation into continuous presence.
        for reminder in self.db.list_context_reminders():
            event = self.db.get_latest_context_event(reminder["uid"])
            if not event:
                continue
            try:
                age = (current - _event_time(event)).total_seconds()
            except (ValueError, TypeError):
                continue
            if not 0 <= age <= 300:
                continue
            event = {**event, "event_id": f"context:{event['id']}:{reminder['id']}", "occurred_at": current.isoformat()}
            if self.cloud:
                event["semantic_contexts"] = self.cloud.get_semantic_contexts(reminder["uid"])
            trigger = self._matching_reminder_trigger(reminder["uid"], reminder, event, current)
            if trigger:
                notification, created = self._fire_reminder(reminder["uid"], reminder, event, current, trigger)
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
        semantic = set(str(reminder.get("activity") or "").replace(" ", "").split(",")) & {"DWELLING", "PARKED", "IN_SHOP"}
        if (reminder.get("location_name") or semantic) and not has_location:
            return None
        if has_due and occurred_at < _parse_time(str(reminder["due_at"])):
            return None
        if not (has_location or has_activity or has_due):
            return None

        # Cooldown: skip reminders created less than 5 seconds before the event.
        # Prevents activity-triggered reminders from firing on the same request
        # cycle that created them (e.g. "remind me when walking" while walking).
        created_at_raw = reminder.get("created_at")
        if created_at_raw:
            try:
                created_dt = _parse_time(str(created_at_raw))
                if (occurred_at - created_dt).total_seconds() < 5.0:
                    return None
            except Exception:
                pass

        activity_matched = (
            self._activity_or_session_state_entered(uid, event, str(reminder["activity"]), occurred_at)
            if has_activity else False
        )
        geofence_entered = False

        if has_location and has_activity:
            inside = self._is_inside_geofence(reminder, event)
            geofence_entered = self._geofence_entered(uid, "REMINDER", reminder["id"], reminder, event, occurred_at)
            # Matches if either:
            # 1. User is inside the target location geofence and starts the activity (e.g. stepping out of room/walking inside flats)
            # 2. User enters the geofence from outside while already engaged in the activity
            if not ((inside and activity_matched) or (geofence_entered and activity_matched)):
                return None
        elif has_location:
            geofence_entered = self._geofence_entered(uid, "REMINDER", reminder["id"], reminder, event, occurred_at)
            if not geofence_entered:
                return None
        elif has_activity:
            if not activity_matched:
                return None

        if has_due and occurred_at < _parse_time(str(reminder["due_at"])):
            return None

        trigger_parts = []
        if has_location:
            trigger_parts.append("GEOFENCE_ENTER" if geofence_entered else "GEOFENCE_INSIDE")
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

    def _activity_or_session_state_entered(
        self, uid: str, event: dict[str, Any], expected: str, occurred_at: datetime,
    ) -> bool:
        """Evaluate a compiled reminder policy at a meaningful event boundary.

        Android supplies only physical activities.  PARKED, DWELLING and
        IN_SHOP are durable session facts derived after the event is persisted;
        this keeps natural-language interpretation in the agent while making
        the final notification decision local, explainable and cheap.
        """
        if _activity_entered(event, expected):
            return True
        if str(event.get("transition", "ENTER")).upper() != "ENTER":
            return False

        expected_states = {
            value.strip().upper()
            for value in re.split(r"[,/|]|(?:\bor\b)", expected, flags=re.IGNORECASE)
            if value.strip()
        }
        semantic_states = expected_states.intersection({"PARKED", "DWELLING", "IN_SHOP"})
        if not semantic_states:
            return False
        if "semantic_contexts" in event:
            return any(
                context.get("active") and context.get("state") in semantic_states
                and float(context.get("confidence", 0)) >= 0.8
                and context.get("last_observed_at")
                and 0 <= (occurred_at - _parse_time(str(context["last_observed_at"]))).total_seconds() <= 300
                for context in event["semantic_contexts"]
            )

        session = self.db.get_active_session(uid)
        if not session or str(session.get("status", "")).upper() != "PAUSED":
            return False

        if "PARKED" in semantic_states:
            return True

        paused_at = session.get("paused_at")
        if not paused_at:
            return False
        try:
            dwell_seconds = (occurred_at - _parse_time(str(paused_at))).total_seconds()
        except (TypeError, ValueError):
            return False
        if dwell_seconds < MIN_DWELL_SEC:
            return False
        if "DWELLING" in semantic_states:
            return True
        return "IN_SHOP" in semantic_states and bool(session.get("poi_visits"))

    def _fire_reminder(
        self, uid: str, reminder: dict[str, Any], event: dict[str, Any], occurred_at: datetime,
        trigger: str,
    ) -> tuple[dict[str, Any], bool]:
        body = reminder.get("body")
        if not body or body == reminder["title"]:
            if reminder.get("location_name"):
                body = f"You are at {reminder['location_name']}."
            elif reminder.get("activity"):
                body = f"Activity context: {reminder['activity']}."
            else:
                body = reminder["title"]

        notification_data = {
                "reminder_id": reminder["id"],
                "title": reminder["title"],
                "body": body,
                "trigger_type": trigger,
                "event_id": str(event.get("event_id", "")),
                "payload": {
                    "reminder_id": reminder["id"],
                    "location_name": reminder.get("location_name"),
                    "occurred_at": occurred_at.isoformat(),
                },
            }
        if self.cloud:
            notification, created, saved = self.cloud.commit_reminder_notification(uid, reminder, notification_data)
            if saved:
                self.db.create_reminder(uid, saved)
            return notification, created
        notification, created = self.db.create_notification(uid, notification_data)
        if created:
            patch: dict[str, Any] = {"last_fired_at": occurred_at.isoformat()}
            if reminder.get("one_shot", True):
                patch["status"] = "COMPLETED"
            self.db.update_reminder(uid, reminder["id"], patch)

            # Sibling auto-completion: If this one-shot reminder fired, also complete any other
            # active reminders for this user with the same normalized title (e.g. alternative travel
            # modes created for the same task) so the user is not spammed with duplicate alerts.
            if reminder.get("one_shot", True):
                rem_title = str(reminder.get("title", "")).strip().lower()
                if rem_title:
                    for other in self.db.list_reminders(uid, status="ACTIVE"):
                        if other["id"] != reminder["id"] and str(other.get("title", "")).strip().lower() == rem_title:
                            self.db.update_reminder(
                                uid, other["id"], {"status": "COMPLETED", "last_fired_at": occurred_at.isoformat()}
                            )
            logger.info(
                "🔔 [REMINDER_FIRED] Reminder triggered | ID: %s | Title: %s | Trigger: %s",
                reminder["id"], reminder["title"], trigger,
            )
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

    def _is_inside_geofence(self, trigger: dict[str, Any], event: dict[str, Any]) -> bool:
        location = event.get("location") or event.get("gps") or event.get("journey_gps", {}).get("end_location") or {}
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        target_latitude = trigger.get("latitude")
        target_longitude = trigger.get("longitude")
        if None in (latitude, longitude, target_latitude, target_longitude):
            return False

        radius_m = float(trigger.get("radius_m", 150.0))
        return _haversine_m(float(latitude), float(longitude), float(target_latitude), float(target_longitude)) <= radius_m

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
    transition = str(event.get("transition", "ENTER")).upper()
    if transition != "ENTER":
        return False
    event_act = str(event.get("activity", "")).upper()
    if not event_act:
        return False
    expected_acts = [
        act.strip().upper()
        for act in re.split(r"[,/|]|(?:\bor\b)", expected, flags=re.IGNORECASE)
        if act.strip()
    ]
    return event_act in expected_acts


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
