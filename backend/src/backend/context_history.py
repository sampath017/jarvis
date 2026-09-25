"""Bounded historical queries and evidence-based timelines for the assistant."""
from datetime import datetime, timedelta, timezone
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


def build_timeline(records: list[dict[str, Any]], start: datetime, end: datetime, *, truncated: bool = False) -> dict:
    """Group repeated samples, without filling unsampled gaps or inventing actions."""
    points = []
    for record in records:
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
        key = (record.get("activity", "UNKNOWN"), record.get("transition", "ENTER"),
               record.get("mobility_session_id"), tuple(inferred), tuple(nearby), tuple(places))
        if episodes and episodes[-1]["_key"] == key and (at - previous).total_seconds() <= 600:
            episodes[-1]["last_observed_at"] = at.isoformat()
            episodes[-1]["samples"] += 1
        else:
            episodes.append({
                "_key": key, "first_observed_at": at.isoformat(), "last_observed_at": at.isoformat(),
                "activity": key[0], "transition": key[1], "session_id": key[2],
                "inferred_contexts": inferred, "nearby_not_confirmed_visits": nearby,
                "saved_place_matches": places, "samples": 1,
            })
        previous = at
    if (end - previous).total_seconds() > 600:
        gaps.append({"from": previous.isoformat(), "to": end.isoformat()})
    for episode in episodes:
        episode.pop("_key")
    return {
        "window_start": start.isoformat(), "window_end": end.isoformat(), "timezone": "UTC",
        "observation_count": len(points), "timeline": episodes[:300],
        "truncated": truncated or len(episodes) > 300,
        "unobserved_gaps_over_10_minutes": gaps[:100], "gap_count": len(gaps),
        "interpretation": "Sampled phone observations only. Intervals are first/last samples, not proof of continuous activity. "
                          "STILL is not proof of sitting; nearby places are not visits; shop context is inferred, not a purchase. "
                          "Missing data means unknown, not inactive. If truncated, query smaller windows before a complete recap.",
    }
