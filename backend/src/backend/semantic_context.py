"""Structured, low-power semantic context for location-aware automations.

This module deliberately does *not* inspect a user's chat text or POI display
names.  A conversational agent may translate a request into a
``ReminderPolicy`` and a place provider may attach a structured
``SemanticPlace``.  The reducer only combines those bounded facts with
activity/session evidence.  This keeps the runtime predictable, auditable,
and cheap enough to run on transition events rather than a continuous GPS/LLM
polling loop.

The objects are serialisable dictionaries so an application can store them in
SQLite/Firestore alongside mobility sessions without coupling the reducer to a
particular persistence implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Iterable


class SemanticContextState(str, Enum):
    """States the agent can reason about as facts, not inferred words."""

    PARKED = "PARKED"
    DWELLING = "DWELLING"
    IN_SHOP = "IN_SHOP"


class SemanticPlaceKind(str, Enum):
    """Canonical place classifications supplied by a trusted resolver."""

    UNKNOWN = "UNKNOWN"
    SHOP = "SHOP"
    HOME = "HOME"
    WORK = "WORK"
    TRANSIT = "TRANSIT"
    OUTDOOR = "OUTDOOR"


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    accuracy_m: float = 25.0


@dataclass(frozen=True)
class SemanticPlace:
    """Resolved place meaning from a POI/geocoding/agent provider.

    ``kind`` must be a canonical enum emitted by the provider.  ``label`` is
    presentation-only and is intentionally never used to classify a context.
    """

    kind: SemanticPlaceKind = SemanticPlaceKind.UNKNOWN
    confidence: float = 0.0
    place_id: str | None = None
    label: str | None = None

    def is_reliable(self, threshold: float) -> bool:
        return self.kind is not SemanticPlaceKind.UNKNOWN and self.confidence >= threshold


@dataclass(frozen=True)
class SemanticObservation:
    """A compact observation sent only on a meaningful device event."""

    event_id: str
    occurred_at: datetime
    activity: str = "UNKNOWN"
    location: GeoPoint | None = None
    mobility_session_id: str | None = None
    mobility_status: str | None = None
    parking_location: GeoPoint | None = None
    place: SemanticPlace | None = None


@dataclass
class SemanticContext:
    """One independently retained context (parking, dwell, or shop visit)."""

    context_id: str
    state: SemanticContextState
    anchor: GeoPoint | None
    entered_at: datetime
    last_observed_at: datetime
    confidence: float
    mobility_session_id: str | None = None
    place: SemanticPlace | None = None
    last_event_id: str | None = None
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        for key in ("entered_at", "last_observed_at"):
            result[key] = result[key].isoformat()
        if self.place:
            result["place"]["kind"] = self.place.kind.value
        return result


@dataclass(frozen=True)
class ContextChange:
    """Result consumed by the orchestration layer to decide whether to wake it."""

    context: SemanticContext
    created: bool
    changed: bool
    reason: str

    @property
    def should_evaluate_agent(self) -> bool:
        """Only a new/semantic transition deserves an agent invocation."""
        return self.created or self.changed


class PredicateKind(str, Enum):
    """Allow-listed condition primitives an agent may put in a policy."""

    CONTEXT_STATE = "CONTEXT_STATE"
    PLACE_KIND = "PLACE_KIND"
    AT_LOCATION = "AT_LOCATION"
    MIN_DWELL_SECONDS = "MIN_DWELL_SECONDS"


@dataclass(frozen=True)
class ReminderCondition:
    """One bounded, structured predicate.  There is no free-text predicate."""

    kind: PredicateKind
    values: tuple[str, ...] = ()
    latitude: float | None = None
    longitude: float | None = None
    radius_m: float | None = None
    seconds: float | None = None

    @classmethod
    def from_agent_plan(cls, value: dict[str, Any]) -> "ReminderCondition":
        """Validate an agent-produced JSON condition before it reaches runtime."""
        try:
            kind = PredicateKind(value["kind"])
        except (KeyError, ValueError) as exc:
            raise ValueError("unknown reminder condition kind") from exc

        raw_values = value.get("values", ())
        if not isinstance(raw_values, (list, tuple)) or not all(isinstance(v, str) for v in raw_values):
            raise ValueError("condition values must be a list of strings")
        values = tuple(raw_values)
        if kind in (PredicateKind.CONTEXT_STATE, PredicateKind.PLACE_KIND) and not values:
            raise ValueError(f"{kind.value} requires at least one value")
        if kind is PredicateKind.CONTEXT_STATE:
            invalid = set(values) - {state.value for state in SemanticContextState}
            if invalid:
                raise ValueError("unknown semantic context state")
        if kind is PredicateKind.PLACE_KIND:
            invalid = set(values) - {place.value for place in SemanticPlaceKind}
            if invalid:
                raise ValueError("unknown semantic place kind")
        if kind is PredicateKind.AT_LOCATION:
            if value.get("latitude") is None or value.get("longitude") is None:
                raise ValueError("AT_LOCATION requires latitude and longitude")
            radius = float(value.get("radius_m", 100.0))
            if not 1.0 <= radius <= 100_000.0:
                raise ValueError("AT_LOCATION radius must be between 1 and 100000 metres")
        if kind is PredicateKind.MIN_DWELL_SECONDS:
            seconds = value.get("seconds")
            if seconds is None or float(seconds) < 0:
                raise ValueError("MIN_DWELL_SECONDS requires a non-negative duration")
        return cls(
            kind=kind,
            values=values,
            latitude=value.get("latitude"),
            longitude=value.get("longitude"),
            radius_m=value.get("radius_m"),
            seconds=value.get("seconds"),
        )


@dataclass(frozen=True)
class ReminderPolicy:
    """An agent-authored policy evaluated deterministically against contexts.

    Every condition must hold.  Alternative user intents should be represented
    as multiple policies, which lets each firing remain explainable.
    """

    policy_id: str
    conditions: tuple[ReminderCondition, ...]
    minimum_confidence: float = 0.65

    @classmethod
    def from_agent_plan(cls, plan: dict[str, Any]) -> "ReminderPolicy":
        raw_conditions = plan.get("conditions")
        if not isinstance(raw_conditions, list) or not raw_conditions:
            raise ValueError("reminder policy needs at least one structured condition")
        confidence = float(plan.get("minimum_confidence", 0.65))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("minimum_confidence must be between zero and one")
        return cls(
            policy_id=str(plan.get("policy_id") or ""),
            conditions=tuple(ReminderCondition.from_agent_plan(item) for item in raw_conditions),
            minimum_confidence=confidence,
        )


@dataclass(frozen=True)
class PolicyEvaluation:
    matched: bool
    unmatched_conditions: tuple[PredicateKind, ...] = ()


def evaluate_reminder_policy(
    policy: ReminderPolicy,
    context: SemanticContext,
    *,
    at: datetime | None = None,
) -> PolicyEvaluation:
    """Evaluate a policy without text parsing, network requests, or model calls."""
    at = _as_utc(at or context.last_observed_at)
    failed: list[PredicateKind] = []
    if not context.active or context.confidence < policy.minimum_confidence:
        return PolicyEvaluation(False, tuple(condition.kind for condition in policy.conditions))

    for condition in policy.conditions:
        if condition.kind is PredicateKind.CONTEXT_STATE:
            matched = context.state.value in condition.values
        elif condition.kind is PredicateKind.PLACE_KIND:
            matched = bool(context.place and context.place.kind.value in condition.values)
        elif condition.kind is PredicateKind.AT_LOCATION:
            matched = bool(
                context.anchor
                and _haversine_m(
                    context.anchor.latitude, context.anchor.longitude,
                    float(condition.latitude), float(condition.longitude),
                ) <= float(condition.radius_m or 100.0) + context.anchor.accuracy_m
            )
        else:  # MIN_DWELL_SECONDS
            matched = (at - _as_utc(context.entered_at)).total_seconds() >= float(condition.seconds or 0.0)
        if not matched:
            failed.append(condition.kind)
    return PolicyEvaluation(not failed, tuple(failed))


class SemanticContextLedger:
    """Keeps multiple active contexts and reduces one structured observation.

    Persist ``contexts`` after each call and restore it with ``from_dicts``.
    The reducer is idempotent per context/event id, so reconnect retries do not
    create duplicate wakeups or reminder evaluations.
    """

    def __init__(
        self,
        contexts: Iterable[SemanticContext] = (),
        *,
        dwell_seconds: float = 90.0,
        stable_radius_m: float = 75.0,
        minimum_place_confidence: float = 0.75,
    ) -> None:
        self.contexts = list(contexts)
        self.dwell_seconds = dwell_seconds
        self.stable_radius_m = stable_radius_m
        self.minimum_place_confidence = minimum_place_confidence

    @classmethod
    def from_dicts(cls, records: Iterable[dict[str, Any]], **kwargs: Any) -> "SemanticContextLedger":
        contexts = []
        for record in records:
            anchor = record.get("anchor")
            place = record.get("place")
            contexts.append(SemanticContext(
                context_id=record["context_id"],
                state=SemanticContextState(record["state"]),
                anchor=GeoPoint(**anchor) if anchor else None,
                entered_at=_parse_datetime(record["entered_at"]),
                last_observed_at=_parse_datetime(record["last_observed_at"]),
                confidence=float(record["confidence"]),
                mobility_session_id=record.get("mobility_session_id"),
                place=SemanticPlace(
                    kind=SemanticPlaceKind(place.get("kind", "UNKNOWN")),
                    confidence=float(place.get("confidence", 0.0)),
                    place_id=place.get("place_id"), label=place.get("label"),
                ) if place else None,
                last_event_id=record.get("last_event_id"), active=bool(record.get("active", True)),
            ))
        return cls(contexts, **kwargs)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [context.to_dict() for context in self.contexts]

    def reduce(self, observation: SemanticObservation) -> list[ContextChange]:
        """Update parking/dwell/shop contexts from a meaningful observation.

        The caller should invoke this from activity transitions, geofence
        transitions, or a one-shot dwell alarm.  It never schedules GPS scans,
        performs I/O, or calls an LLM.
        """
        changes: list[ContextChange] = []
        now = _as_utc(observation.occurred_at)
        if self.contexts and now < max(_as_utc(c.last_observed_at) for c in self.contexts):
            return []
        if observation.mobility_status in {"RESUMED", "COMPLETED", "EXPIRED"}:
            changes.extend(self._deactivate_parked(observation, now))
        elif observation.mobility_status == "PAUSED" and observation.parking_location:
            changes.append(self._upsert_parked(observation, now))

        if observation.location:
            changes.extend(self._deactivate_displaced_visit_contexts(observation, now))
        if observation.activity in {"IN_VEHICLE", "ON_BICYCLE", "RUNNING"}:
            for context in self.contexts:
                if context.active and context.state is not SemanticContextState.PARKED:
                    context.active = False
                    context.last_observed_at = now
                    context.last_event_id = observation.event_id
                    changes.append(ContextChange(context, False, True, "travel_resumed"))
        if observation.location and self._is_stationary_activity(observation.activity):
            dwell = self._upsert_dwell(observation, now)
            if dwell:
                changes.append(dwell)
                if (dwell.context.confidence >= 0.8 and observation.place
                        and observation.place.kind is SemanticPlaceKind.SHOP
                        and observation.place.is_reliable(self.minimum_place_confidence)):
                    changes.append(self._upsert_shop(observation, now, dwell.context))
        return changes

    def _upsert_parked(self, observation: SemanticObservation, now: datetime) -> ContextChange:
        key = f"parked:{observation.mobility_session_id or observation.event_id}"
        current = self._find_by_id(key)
        if current and not current.active:
            key = f"{key}:{observation.event_id}"
            current = self._find_by_id(key)
        active_parking = next((c for c in self.contexts if c.active and c.state is SemanticContextState.PARKED
                               and c.mobility_session_id == observation.mobility_session_id), None)
        if active_parking:
            current = active_parking
        if current:
            if current.last_event_id == observation.event_id:
                return ContextChange(current, False, False, "duplicate_event")
            current.last_observed_at = now
            current.last_event_id = observation.event_id
            return ContextChange(current, False, False, "parking_refreshed")
        context = SemanticContext(
            context_id=key, state=SemanticContextState.PARKED,
            anchor=observation.parking_location, entered_at=now, last_observed_at=now,
            confidence=1.0, mobility_session_id=observation.mobility_session_id,
            last_event_id=observation.event_id,
        )
        self.contexts.append(context)
        return ContextChange(context, True, True, "vehicle_parked")

    def _deactivate_parked(self, observation: SemanticObservation, now: datetime) -> list[ContextChange]:
        changes = []
        for context in self.contexts:
            if (context.active and context.state is SemanticContextState.PARKED
                    and context.mobility_session_id == observation.mobility_session_id):
                context.active = False
                context.last_observed_at = now
                context.last_event_id = observation.event_id
                changes.append(ContextChange(context, False, True, "mobility_session_resumed_or_closed"))
        return changes

    def _upsert_dwell(self, observation: SemanticObservation, now: datetime) -> ContextChange | None:
        current = self._nearest_active(SemanticContextState.DWELLING, observation.location)
        if current is None:
            provisional = SemanticContext(
                context_id=f"dwell:{observation.event_id}", state=SemanticContextState.DWELLING,
                anchor=observation.location, entered_at=now, last_observed_at=now,
                confidence=0.0, mobility_session_id=observation.mobility_session_id,
                place=observation.place, last_event_id=observation.event_id,
            )
            self.contexts.append(provisional)
            # A candidate is retained so the next low-power dwell alarm can
            # confirm it, but must never wake the agent on its own.
            return ContextChange(provisional, False, False, "dwell_candidate_started")
        if current.last_event_id == observation.event_id:
            return ContextChange(current, False, False, "duplicate_event")
        current.last_observed_at = now
        current.last_event_id = observation.event_id
        if observation.place and observation.place.is_reliable(self.minimum_place_confidence):
            current.place = observation.place
        stable_for = (now - _as_utc(current.entered_at)).total_seconds()
        was_confident = current.confidence >= 0.8
        if stable_for >= self.dwell_seconds:
            current.confidence = 0.8
        return ContextChange(current, False, not was_confident and current.confidence >= 0.8, "dwell_confirmed" if current.confidence >= 0.8 else "dwell_candidate_refreshed")

    def _deactivate_displaced_visit_contexts(
        self, observation: SemanticObservation, now: datetime,
    ) -> list[ContextChange]:
        """Close visit contexts only after a location sample clears both error bounds.

        Parking remains independent: walking away from a parked vehicle should
        not erase the vehicle context.  An exit is itself meaningful context,
        but its change can be handled without a fresh model classification.
        """
        assert observation.location is not None
        changes = []
        for context in self.contexts:
            if (not context.active or context.state is SemanticContextState.PARKED
                    or context.anchor is None):
                continue
            distance = _haversine_m(
                context.anchor.latitude, context.anchor.longitude,
                observation.location.latitude, observation.location.longitude,
            )
            boundary = self.stable_radius_m + context.anchor.accuracy_m + observation.location.accuracy_m
            if distance > boundary:
                context.active = False
                context.last_observed_at = now
                context.last_event_id = observation.event_id
                changes.append(ContextChange(context, False, True, "left_context_area"))
        return changes

    def _upsert_shop(self, observation: SemanticObservation, now: datetime, dwell: SemanticContext) -> ContextChange:
        assert observation.place is not None
        key_suffix = observation.place.place_id or dwell.context_id
        key = f"shop:{key_suffix}:{dwell.context_id}"
        current = self._find_by_id(key)
        if current is None:
            current = SemanticContext(
                context_id=key, state=SemanticContextState.IN_SHOP, anchor=dwell.anchor,
                entered_at=dwell.entered_at, last_observed_at=now,
                confidence=min(dwell.confidence, observation.place.confidence),
                mobility_session_id=observation.mobility_session_id,
                place=observation.place, last_event_id=observation.event_id,
            )
            self.contexts.append(current)
            return ContextChange(current, True, True, "reliable_shop_visit")
        if current.last_event_id == observation.event_id:
            return ContextChange(current, False, False, "duplicate_event")
        current.last_observed_at = now
        current.last_event_id = observation.event_id
        current.place = observation.place
        return ContextChange(current, False, False, "shop_visit_refreshed")

    def _nearest_active(self, state: SemanticContextState, location: GeoPoint) -> SemanticContext | None:
        matches = [
            context for context in self.contexts
            if context.active and context.state is state and context.anchor
            and _haversine_m(context.anchor.latitude, context.anchor.longitude, location.latitude, location.longitude)
            <= self.stable_radius_m + max(context.anchor.accuracy_m, location.accuracy_m)
        ]
        return max(matches, key=lambda context: context.last_observed_at) if matches else None

    def _find_by_id(self, context_id: str) -> SemanticContext | None:
        return next((context for context in self.contexts if context.context_id == context_id), None)

    @staticmethod
    def _is_stationary_activity(activity: str) -> bool:
        # Activity is a bounded device classification, never parsed free text.
        return activity in {"STILL", "WALKING"}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_datetime(value: str | datetime) -> datetime:
    return _as_utc(value if isinstance(value, datetime) else datetime.fromisoformat(value))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi, d_lambda = radians(lat2 - lat1), radians(lon2 - lon1)
    value = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return radius * 2 * atan2(sqrt(value), sqrt(1 - value))
