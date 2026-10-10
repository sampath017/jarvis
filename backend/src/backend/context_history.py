"""Bounded historical queries and evidence-based timelines for the assistant."""
from datetime import datetime, timedelta, timezone
import re
from typing import Any


def utc_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Include a timezone offset in history timestamps")
    return parsed.astimezone(timezone.utc)


def history_window(lookback_minutes: int = 2880, start_at: str = "", end_at: str = ""):
    end = utc_time(end_at) if end_at else datetime.now(timezone.utc)
    if not 1 <= lookback_minutes <= 44640:
        raise ValueError("History lookback must be between 1 minute and 31 days")
    start = utc_time(start_at) if start_at else end - timedelta(minutes=lookback_minutes)
    if start >= end or end - start > timedelta(days=31):
        raise ValueError("Choose a positive history window of at most 31 days")
    return start, end


def prefetch_history_window(text: str, now: datetime | None = None):
    """Prefetch only an explicit, unambiguous personal activity recap window.

    The agent still interprets the question and may request a different window.
    This saves a model round spent asking for history already named by the user.
    """
    text = text.lower()
    if re.search(r'\b(remind|reminder|create|save|delete|update|schedule)\b', text):
        return None
    if not re.search(r'\b(did|doing|done|activity|activities|trip|ride|riding|walked|walking|went|recap|history|timeline)\b', text):
        return None
    relative = re.findall(r'\blast\s+(\d+)\s+(minutes?|hours?|days?)\b', text)
    calendars = re.findall(r'\b(today|yesterday)\b', text)
    if len(relative) + len(calendars) != 1:
        return None
    end = utc_time(now or datetime.now(timezone.utc))
    if relative:
        count, unit = relative[0]
        minutes = int(count) * (1440 if unit.startswith('day') else 60 if unit.startswith('hour') else 1)
        if not 1 <= minutes <= 44640:
            return None
        return end - timedelta(minutes=minutes), end
    local = end.astimezone(timezone(timedelta(hours=5, minutes=30)))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if calendars[0] == 'yesterday':
        return utc_time(midnight - timedelta(days=1)), utc_time(midnight)
    return utc_time(midnight), end


def build_timeline(records: list[dict[str, Any]], start: datetime, end: datetime, *, truncated: bool = False) -> dict:
    """Group repeated samples, without filling unsampled gaps or inventing actions."""
    from .activity_evidence import qualified_records
    points = []
    records = qualified_records(records)
    for record in records:
        if record.get('source') == 'user_report' or record.get('activity_evidence') == 'diagnostic_event':
            continue  # A correction must not disguise a gap in phone coverage.
        try:
            at = utc_time(record["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        if start <= at <= end:
            points.append((at, record))
    points.sort(key=lambda item: item[0])
    episodes: list[dict] = []
    gaps = []
    previous = start
    for at, record in points:
        if (at - previous).total_seconds() > 600:
            gaps.append({"from": previous.isoformat(), "to": at.isoformat()})
        contexts = record.get("contexts") or []
        inferred = sorted({c.get("state") for c in contexts if c.get("state") and c.get("active")
                           and c.get("confidence", 0) >= 0.8})
        nearby = sorted({str(p["name"]) for p in record.get("nearby_candidates", []) if p.get("name")})
        places = sorted({str(p["name"]) for p in record.get("saved_places", []) if p.get("name")})
        gps = record.get("gps") or {}
        location = ({"observed_at": gps.get("timestamp") or at.isoformat(), "activity_observed_at": at.isoformat(), **gps}
                    if gps.get("latitude") is not None and gps.get("longitude") is not None else None)
        key = (record.get("activity", "UNKNOWN"), record.get("transition", "ENTER"),
               record.get("mobility_session_id"), tuple(inferred), tuple(nearby), tuple(places))
        if episodes and episodes[-1]["_key"] == key and (at - previous).total_seconds() <= 600:
            episodes[-1]["last_observed_at"] = at.isoformat()
            episodes[-1]["samples"] += 1
            if location:
                episodes[-1]["location_observations"].append(location)
        else:
            episodes.append({
                "_key": key, "first_observed_at": at.isoformat(), "last_observed_at": at.isoformat(),
                "activity": key[0], "transition": key[1], "session_id": key[2],
                "inferred_contexts": inferred, "nearby_not_confirmed_visits": nearby,
                "saved_place_matches": places, "samples": 1,
                "location_observations": [location] if location else [],
            })
        previous = at
    if (end - previous).total_seconds() > 600:
        gaps.append({"from": previous.isoformat(), "to": end.isoformat()})
    for episode in episodes:
        episode.pop("_key")
    return {
        "window_start": start.isoformat(), "window_end": end.isoformat(), "timezone": "UTC",
        "observation_count": len(points), "timeline": episodes[:300],
        "observations_with_gps": sum((r.get("gps") or {}).get("latitude") is not None
                                     and (r.get("gps") or {}).get("longitude") is not None for _, r in points),
        "truncated": truncated or len(episodes) > 300,
        "records_truncated": truncated, "timeline_truncated": len(episodes) > 300,
        "unobserved_gaps_over_10_minutes": gaps[:100], "gap_count": len(gaps),
        "interpretation": "Phone sensor classifications can be wrong and must not overrule the user's reported activity. "
                          "An unpaired EXIT is not proof the user performed that activity. Cached labels are UNKNOWN, not fresh measurements. "
                          "Sampled phone observations only. Intervals are first/last samples, not proof of continuous activity. "
                          "STILL is not proof of sitting; nearby places are not visits; shop context is inferred, not a purchase. "
                          "Missing data means unknown, not inactive. If truncated, query smaller windows before a complete recap.",
    }
