"""Enums for activity types, session states, vehicle classes, CRUD entities, and request types."""

from __future__ import annotations

from enum import Enum


class ActivityType(str, Enum):
    """Android Activity Recognition transition types."""
    STILL = "STILL"
    WALKING = "WALKING"
    RUNNING = "RUNNING"
    IN_VEHICLE = "IN_VEHICLE"
    ON_BICYCLE = "ON_BICYCLE"
    TILTING = "TILTING"
    UNKNOWN = "UNKNOWN"


class TransitionType(str, Enum):
    """Activity transition direction."""
    ENTER = "ENTER"
    EXIT = "EXIT"


class SessionStatus(str, Enum):
    """Journey session lifecycle states."""
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class VehicleClass(str, Enum):
    """Vehicle classification results."""
    HUNTER_350 = "HUNTER_350"
    OTHER_MOTORCYCLE = "OTHER_MOTORCYCLE"
    CAR = "CAR"
    BUS = "BUS"
    UNKNOWN = "UNKNOWN"
    NOT_VEHICLE = "NOT_VEHICLE"


class Tier1Action(str, Enum):
    """Recommended actions from Tier 1 reasoner."""
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    COMPLETE = "COMPLETE"
    RECLASSIFY = "RECLASSIFY"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class CRUDEntity(str, Enum):
    """Supported CRUD entity types."""
    TASK = "TASK"
    NOTE = "NOTE"
    PLACE = "PLACE"
    SESSION = "SESSION"
    PREFERENCE = "PREFERENCE"
    AUTOMATION = "AUTOMATION"
    EVENT = "EVENT"
    REMINDER = "REMINDER"
    NOTIFICATION = "NOTIFICATION"
    CONTEXT_RULE = "CONTEXT_RULE"


class CRUDOperation(str, Enum):
    """CRUD operation types."""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LIST = "LIST"


class RequestType(str, Enum):
    """LangGraph workflow entry point types."""
    CONTEXT_EVENT = "CONTEXT_EVENT"
    USER_COMMAND = "USER_COMMAND"
