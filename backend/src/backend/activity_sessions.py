"""Revisable activity sessions learned from observed stops, places and radio anchors.

Raw observations remain the source of truth. Rebuilding in event-time order lets
late uploads correct intervals and boundaries rather than permanently splitting
an outing. No wall-clock inactivity timeout is used to end a session.
"""
from __future__ import annotations

from collections import defaultdict
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from statistics import median
from typing import Any

from .context_history import utc_time

MOTION = {"STILL", "WALKING", "RUNNING", "ON_BICYCLE", "IN_VEHICLE", "ON_FOOT"}
LOCAL = timezone(timedelta(hours=5, minutes=30))


def _distance(a, b):
    p, q = radians(a[0]), radians(b[0])
    return 12_742_000 * asin(min(1, sqrt(sin((q-p)/2)**2 + cos(p)*cos(q)*sin(radians(b[1]-a[1])/2)**2)))


def _place(record, anchors):
    for place in record.get("saved_places") or []:
        label = str(place.get("user_label") or place.get("category") or "").upper()
        return "saved:" + str(place.get("id") or place.get("name")), label == "HOME"
    ambient = record.get("ambient_context") or {}
    if ambient.get("collected_at"):
        try:
            if abs((utc_time(ambient["collected_at"]) - utc_time(record["timestamp"])).total_seconds()) > 60:
                ambient = {}
        except (ValueError, TypeError):
            ambient = {}
    connected = (ambient.get("wifi") or {}).get("connected") or {}
    if connected.get("id") and connected.get("age_ms", 0) <= 120_000:
        return "wifi:" + connected["id"], False
    nearby = (ambient.get("bluetooth") or {}).get("nearby") or []
    beacons = sorted(d["id"] for d in nearby if d.get("id") and d.get("rssi", -999) >= -75
                     and d.get("age_ms", 0) <= 120_000)
    if len(beacons) >= 2:
        return "radio:" + sha256("|".join(beacons[:6]).encode()).hexdigest()[:16], False
    gps = record.get("gps") or {}
    if gps.get("latitude") is not None and gps.get("longitude") is not None and gps.get("accuracy_m", 999) <= 150:
        point = (gps["latitude"], gps["longitude"])
        for key, anchor in anchors.items():
            if _distance(point, anchor) <= max(80, gps.get("accuracy_m", 0)):
                return key, False
        key = "area:" + sha256(f"{point[0]:.4f},{point[1]:.4f}".encode()).hexdigest()[:16]
        anchors[key] = point
        if len(anchors) > 128:
            anchors.pop(next(iter(anchors)))
        return key, False
    return None, False


def _moments(records):
    from .activity_evidence import qualified_records, compatible_motion
    records = qualified_records(records)
    ordered = []
    for record in records:
        try:
            ordered.append((utc_time(record["timestamp"]), record))
        except (KeyError, TypeError, ValueError):
            continue
    ordered.sort(key=lambda pair: (pair[0], pair[1].get("transition") != "EXIT", str(pair[1].get("event_id", ""))))
    anchors, moments, active = {}, [], {}
    for at, record in ordered:
        if record.get('activity_evidence') == 'user_reported':
            try:
                reported_end = utc_time(record['reported_end_at'])
            except (KeyError, TypeError, ValueError):
                continue
            if reported_end <= at:
                continue
            moments.append({'moment_id': sha256(str(record['event_id']).encode()).hexdigest()[:24],
                'activity': record['activity'], 'axis': 'reported', 'evidence_status': 'user_reported',
                'start_at': at.isoformat(), 'end_at': reported_end.isoformat(),
                'last_observed_at': reported_end.isoformat(), 'start_evidence': 'user_reported',
                'end_evidence': 'user_reported', 'event_ids': [record['event_id']],
                'observations': [], 'place_key': None, 'home': False})
            continue
        activity = str(record.get("activity") or "UNKNOWN").upper()
        event_type = record.get("event_type") or ""
        axis = "call" if event_type in {"CALL_START", "CALL_END"} else "motion"
        if axis == "call":
            activity = "PHONE_CALL"
        elif activity not in MOTION:
            activity = "UNKNOWN"
        transition = record.get("transition", "ENTER")
        genuine = event_type in {"ACTIVITY_ENTER", "ACTIVITY_EXIT", "ACTIVITY_TRANSITION", "CALL_START", "CALL_END"}
        current = active.get(axis)
        if record.get('activity_evidence') == 'diagnostic_event':
            continue
        if (axis == 'motion' and current and genuine and transition != 'EXIT'
                and current['activity'] == activity
                and (at - utc_time(current['last_observed_at'])).total_seconds() > 600):
            # A new start after an unobserved period does not imply the previous
            # occurrence continued. A matching EXIT, however, retains its pair.
            current['end_at'] = current['last_observed_at']
            current['end_evidence'] = 'new_start_after_gap'
            active.pop(axis, None)
            current = None
        # A cached checkpoint carries location/radio evidence, not a new motion
        # measurement. It must never extend or train a stationary/walking span.
        if record.get('activity_evidence') in {'cached_state', 'unpaired_exit', 'uncertain_sample'}:
            if record.get('activity_evidence') == 'uncertain_sample' and current:
                current.setdefault('uncertain_observations', []).append(at.isoformat())
                current['event_ids'].append(record.get('event_id'))
            continue
        if activity == 'UNKNOWN' and axis == 'motion':
            if current:
                current.setdefault('uncertain_observations', []).append(at.isoformat())
            continue
        if (current and axis == 'motion' and not genuine
                and compatible_motion(current['activity'], activity)):
            activity = current['activity']
        if transition == "EXIT":
            if current and current["activity"] == activity:
                current["end_at"] = at.isoformat()
                current["end_evidence"] = "detected_exit"
            else:
                continue
        else:
            if current and current["activity"] != activity:
                current["end_at"] = at.isoformat()
                current["end_evidence"] = "next_detected_activity" if genuine else "next_observation"
                current = None
            if current is None:
                event_id = str(record.get("event_id") or f"{activity}:{at.isoformat()}")
                current = {"moment_id": sha256(event_id.encode()).hexdigest()[:24], "activity": activity,
                           "evidence_status": "sensor_classification",
                           "axis": axis, "start_at": at.isoformat(), "end_at": None,
                           "start_evidence": "detected_enter" if genuine else "observation",
                           "end_evidence": None, "event_ids": [], "observations": [],
                           "place_key": None, "home": False}
                moments.append(current)
                active[axis] = current
        place_key, home = _place(record, anchors)
        # Keep the first reliable anchor. A later location is a separate sample,
        # never an invented location at the start of the moment.
        if not current["place_key"] and place_key:
            current["place_key"], current["home"] = place_key, home
        current["event_ids"].append(record.get("event_id"))
        current["observations"].append({"timestamp": at.isoformat(), "gps": record.get("gps"),
                                        "activity": record.get("activity"),
                                        "activity_evidence": record.get("activity_evidence"),
                                        "activity_confidence": record.get("activity_confidence"),
                                        "event_type": record.get("event_type"),
                                        "ambient_context": record.get("ambient_context") or {},
                                        "location_status": record.get("location_status")})
        current["last_observed_at"] = at.isoformat()
        if activity == "UNKNOWN":
            current["end_at"] = at.isoformat()
            current["end_evidence"] = "observation_only"
            active.pop(axis, None)
        if transition == "EXIT":
            active.pop(axis, None)
    for moment in moments:
        _attach_coverage(moment)
    return sorted(moments, key=lambda m: (m["start_at"], m["axis"]))


def _attach_coverage(moment):
    """Describe missing evidence without converting uncertainty into an exit."""
    start = utc_time(moment['start_at'])
    end = utc_time(moment.get('end_at') or moment['last_observed_at'])
    moment['classified_span_seconds'] = max(0, (end - start).total_seconds())
    points = sorted({start, end, *(utc_time(o['timestamp']) for o in moment['observations'])})
    uncertain = sorted(utc_time(t) for t in moment.get('uncertain_observations', []))
    gaps = []
    if moment['axis'] == 'motion':
        for left, right in zip(points, points[1:]):
            pos = bisect_left(uncertain, left)
            noisy = pos < len(uncertain) and uncertain[pos] <= right
            if noisy or (right - left).total_seconds() > 600:
                gaps.append({'from': left.isoformat(), 'to': right.isoformat(),
                             'reason': 'uncertain_samples' if noisy else 'observation_gap'})
    moment['coverage_gaps'] = gaps
    moment['uncertain_seconds'] = sum((utc_time(g['to']) - utc_time(g['from'])).total_seconds() for g in gaps)
    moment['coverage_status'] = 'uncertain' if gaps or uncertain else 'sampled'


def _routine_key(moment):
    at = utc_time(moment["start_at"]).astimezone(LOCAL)
    return f"{moment['place_key']}:{'weekend' if at.weekday() >= 5 else 'weekday'}:{at.hour // 6}"


def build_activity_sessions(records: list[dict[str, Any]], learned_stops: list[dict] | None = None) -> dict:
    moments = _moments(records)
    # Learn only completed, detected stationary spans; missing events and open
    # tails cannot train a fictitious routine. Each span contributes once.
    stop_samples = {}
    for sample in learned_stops or []:
        try:
            if (sample.get("moment_id") and sample.get("place_key") and sample.get("routine_key")
                    and 0 < float(sample["duration"]) < float("inf")):
                utc_time(sample["end_at"])
                stop_samples[sample["moment_id"]] = sample
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    for moment in moments:
        if moment["activity"] != "STILL" or not moment["place_key"] or not moment["end_at"]:
            continue
        duration = (utc_time(moment["end_at"]) - utc_time(moment["start_at"])).total_seconds()
        if (duration > 0 and moment.get('coverage_status') != 'uncertain' and moment["start_evidence"] == "detected_enter"
                and moment["end_evidence"] in {"detected_exit", "next_detected_activity"}):
            stop_samples[moment["moment_id"]] = {"moment_id": moment["moment_id"], "end_at": moment["end_at"],
                "duration": duration, "place_key": moment["place_key"], "routine_key": _routine_key(moment)}
    samples = sorted(stop_samples.values(), key=lambda s: s["end_at"])[-512:]
    completed = defaultdict(list)
    for sample in samples:
        for key in {sample["routine_key"], str(sample["place_key"]), "global"}:
            completed[key].append(sample["duration"])
    groups, current, has_movement = [], None, False
    calls = [m for m in moments if m["axis"] == "call"]
    for moment in moments:
        if moment["axis"] == "call":
            continue
        if current is None:
            has_movement = False
            current = {"session_id": "activity_" + moment["moment_id"], "started_at": moment["start_at"],
                       "last_updated": moment["last_observed_at"], "completed_at": None,
                       "status": "PROVISIONAL", "boundary_reason": "learning_new_routine", "moment_ids": []}
            groups.append(current)
        current["moment_ids"].append(moment["moment_id"])
        moment["session_id"] = current["session_id"]
        current["last_updated"] = max(current["last_updated"], moment["last_observed_at"])
        if moment["activity"] != "STILL":
            has_movement = has_movement or moment["activity"] in (MOTION - {"STILL"})
            continue
        start = utc_time(moment["start_at"])
        observed_end = utc_time(moment.get("end_at") or moment["last_observed_at"])
        duration = (observed_end - start).total_seconds()
        place_key = moment["place_key"]
        routine_key = _routine_key(moment)
        prior = [s for s in samples if utc_time(s["end_at"]) <= start and s["moment_id"] != moment["moment_id"]]
        candidates, basis = [s["duration"] for s in prior if s["routine_key"] == routine_key], "place_and_schedule"
        if len(candidates) < 3:
            candidates, basis = [s["duration"] for s in prior if s["place_key"] == place_key], "place"
        if len(candidates) < 3:
            candidates, basis = [s["duration"] for s in prior], "personal_stop_history"
        threshold = sorted(candidates)[int((len(candidates)-1)*.75)] if len(candidates) >= 3 else None
        occupied = any(utc_time(c["start_at"]) <= observed_end and
                       (c["end_at"] is None or utc_time(c["end_at"]) > observed_end) for c in calls)
        settled = (place_key and not occupied and has_movement and moment.get('coverage_status') != 'uncertain' and len(moment["observations"]) >= 2
                   and threshold is not None and duration >= threshold)
        # Cold start still works from strong place evidence: arriving at a
        # user-labelled home plus repeated stationary observations can settle
        # an outing even before a personal duration distribution exists.
        home_arrival = (threshold is None and moment["home"] and not occupied and has_movement and moment.get('coverage_status') != 'uncertain'
                        and len(moment["observations"]) >= 2)
        if settled or home_arrival:
            current.update(status="SETTLED", completed_at=observed_end.isoformat(),
                           boundary_reason="confirmed_home_arrival" if home_arrival else "learned_" + basis,
                           learned_stop_seconds=threshold)
            current = None
    # Calls are independent overlays, not a replacement for walking/stationary.
    for call in calls:
        owning = [g for g in groups if g["started_at"] <= call["start_at"]]
        if owning:
            group = owning[-1]
            call["session_id"] = group["session_id"]
            group["moment_ids"].append(call["moment_id"])
            group["last_updated"] = max(group["last_updated"], call["last_observed_at"])
        else:
            group = {"session_id": "activity_" + call["moment_id"], "started_at": call["start_at"],
                     "last_updated": call["last_observed_at"], "completed_at": None, "status": "PROVISIONAL",
                     "boundary_reason": "call_without_motion_observations", "moment_ids": [call["moment_id"]]}
            groups.append(group)
            call["session_id"] = group["session_id"]
    routines = [{"context": key, "completed_stops": len(values), "median_stop_seconds": median(values)}
                for key, values in completed.items() if values]
    return {"micromoments": moments, "activity_sessions": sorted(groups, key=lambda g: g["started_at"]),
            "routine_learning": {"evidence_version": 3, "status": "LEARNING" if len(completed["global"]) < 3 else "ADAPTING",
                                 "completed_stops": len(completed["global"]), "routines": routines,
                                 "stop_samples": samples},
            "session_interpretation": "Session boundaries are provisional and revisable from event history. "
            "Stop thresholds learn from past detected stops at similar places and times, never a fixed inactivity timer. "
            "Sensor classifications are not confirmed human actions and can be contradicted by the user. "
            "Unpaired exit events do not establish walking or any other activity. "
            "Stationary does not establish sitting. A phone call does not establish speech content. "
            "Logical sessions retain matching transitions across uncertain samples. coverage_gaps and uncertain_seconds "
            "mark unverified portions; exclude them from supported duration totals. "
            "ON_FOOT without an explicit walking start is not WALKING. "
            "Open moments describe last detected state, not proof of uninterrupted activity."}


def enriched_history(fs, uid, start, end, *, persist=False):
    """Use a bounded history to learn routines and seed activity before a recap."""
    from .context_history import build_timeline
    profile_available = True
    try:
        profile = fs.get_activity_routines(uid)
    except Exception:
        profile, profile_available = {}, False
    learned = profile.get("stop_samples", []) if isinstance(profile, dict) and profile.get('evidence_version') == 3 else []
    # Read the requested window completely, subdividing dense windows instead
    # of silently supplying only the newest 5,000 records to the assistant.
    records, truncated = complete_window_records(fs, uid, start, end)
    # A bounded prelude can seed an activity that began before the requested
    # window. Missing older training data does not truncate this window.
    prelude, prelude_truncated = fs.query_context_memory(uid, start - timedelta(days=2), start, recent_first=True)
    records = _unique_records([*prelude, *records])
    from .activity_evidence import qualified_records
    records = qualified_records(records)
    result = build_timeline(records, start, end, truncated=truncated)
    analysis = build_activity_sessions(records, learned)
    visible = [m for m in analysis["micromoments"]
               if utc_time(m.get("end_at") or m["last_observed_at"]) >= start and utc_time(m["start_at"]) <= end]
    for moment in visible:
        moment["window_start_at"] = max(start, utc_time(moment["start_at"])).isoformat()
        moment["window_end_at"] = min(end, utc_time(moment.get("end_at") or moment["last_observed_at"])).isoformat()
        moment['window_uncertain_seconds'] = sum(max(0, (min(end, utc_time(g['to'])) - max(start, utc_time(g['from']))).total_seconds())
                                                  for g in moment.get('coverage_gaps', []))
    session_ids = {m["session_id"] for m in visible}
    result.update({**analysis, "micromoments": visible,
                   "activity_sessions": [s for s in analysis["activity_sessions"] if s["session_id"] in session_ids]})
    result['activity_totals'] = activity_totals(visible, start, end)
    result['session_history_truncated'] = truncated
    result['truncated'] = truncated  # Only the legacy timeline preview is capped.
    result['prelude_truncated'] = prelude_truncated
    # Routine samples are durable training state, not material for every model
    # answer. Keep only a compact learning summary in API/LLM context.
    result["routine_learning"] = {k: analysis["routine_learning"][k] for k in ("status", "completed_stops")}
    if persist and not truncated and not prelude_truncated and profile_available:
        fs.save_activity_analysis(uid, analysis, end)
    return result, records


def _unique_records(records):
    unique = {}
    for r in records:
        key = r.get('event_id') or (str(r.get('timestamp')), r.get('event_type'), r.get('activity'), r.get('transition'))
        unique[key] = r
    return sorted(unique.values(), key=lambda r: utc_time(r['timestamp']))


def complete_window_records(fs, uid, start, end, max_queries=64):
    pending, records, incomplete, queries = [(start, end)], [], False, 0
    while pending:
        left, right = pending.pop()
        batch, truncated = fs.query_context_memory(uid, left, right, recent_first=True)
        queries += 1
        if truncated and (right - left).total_seconds() > 1 and queries + len(pending) + 2 <= max_queries:
            middle = left + (right - left) / 2
            pending.extend([(middle, right), (left, middle)])
        else:
            records.extend(batch)
            incomplete = incomplete or truncated
    return _unique_records(records), incomplete


def activity_totals(moments, start, end):
    """Totals are classified session spans, with unknown coverage kept explicit."""
    totals = {}
    for moment in moments:
        left = max(start, utc_time(moment['start_at']))
        right = min(end, utc_time(moment.get('end_at') or moment['last_observed_at']))
        if right < left:
            continue
        key = moment['activity']
        row = totals.setdefault(key, {'session_count': 0, 'classified_span_seconds': 0,
                                     'uncertain_seconds': 0, 'open_sessions': 0})
        row['session_count'] += 1
        row['classified_span_seconds'] += (right-left).total_seconds()
        row['open_sessions'] += int(not moment.get('end_at'))
        for gap in moment.get('coverage_gaps', []):
            row['uncertain_seconds'] += max(0, (min(right, utc_time(gap['to'])) - max(left, utc_time(gap['from']))).total_seconds())
    return totals


def compact_observation(record):
    """Radio identities feed the reducer; the assistant needs their evidence summary."""
    result = dict(record)
    ambient = result.get("ambient_context") or {}
    if ambient:
        summary = {"collected_at": ambient.get("collected_at")}
        for key in ("wifi", "bluetooth"):
            radio = ambient.get(key) or {}
            connected = radio.get("connected")
            summary[key] = {"status": radio.get("status"), "nearby_count": len(radio.get("nearby") or []),
                            "connected_count": len(connected) if isinstance(connected, list) else int(bool(connected)),
                            "connection_change": radio.get("connection_change")}
        result["ambient_context"] = summary
    return result


def compact_history(history):
    result = dict(history)
    result["micromoments"] = [{k: ([compact_observation(o) for o in value] if k == "observations" else value)
                               for k, value in moment.items() if k not in {"event_ids", "moment_id"}}
                              for moment in history.get("micromoments", [])]
    return result
