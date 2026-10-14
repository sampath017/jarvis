"""Canonical chat creation time, including the original Android local format."""
from datetime import datetime, timedelta, timezone
import re

LEGACY_PHONE_TZ = timezone(timedelta(hours=5, minutes=30))


def message_time(value, *, message_id=None, role=None):
    # Android msg_<epoch microseconds> IDs encode the send instant. The server
    # used to overwrite it with completion time, sometimes after the reply.
    if role == 'user' and re.fullmatch(r'msg_\d{16}', str(message_id or '')):
        micros = int(message_id[4:])
        instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros)
        if 2020 <= instant.year <= 2100:
            return instant
    instant = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        # Only legacy chat records use this compatibility rule. Other event,
        # scheduler and inactivity timestamps keep their strict validation.
        instant = instant.replace(tzinfo=LEGACY_PHONE_TZ)
    return instant.astimezone(timezone.utc)


def message_stamp(value, **kwargs):
    return message_time(value, **kwargs).isoformat(timespec='microseconds')
