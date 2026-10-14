"""Deterministic inactivity rules; no model call is needed to assess chat use."""
from datetime import datetime, timezone

INACTIVE_DAYS = 30
ACTIVITY_FIELDS = ('archive_activity_at', 'last_used_at', 'updated_at', 'created_at')


def timestamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def last_activity(data):
    values = []
    for name in ACTIVITY_FIELDS:
        if data.get(name) is not None:
            value = timestamp(data[name])
            if value is None:
                return None  # Unknown timestamps must not make a chat eligible.
            values.append(value)
    return max(values) if values else None


def inactive(data, cutoff):
    value = last_activity(data)
    return value is not None and value <= cutoff


def activity_fingerprint(data):
    return tuple(timestamp(data.get(name)) for name in ACTIVITY_FIELDS)
