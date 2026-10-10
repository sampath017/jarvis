"""Render explicit activity recaps from verified tool evidence, without a model call."""
import json
import re
from datetime import datetime, timedelta, timezone

from .context_history import prefetch_history_window, utc_time

IST = timezone(timedelta(hours=5, minutes=30))
ACTIVITIES = {'WALKING': 'Walking', 'RUNNING': 'Running', 'STILL': 'Stationary',
              'IN_VEHICLE': 'In a vehicle', 'ON_BICYCLE': 'Cycling', 'ON_FOOT': 'On foot',
              'PHONE_CALL': 'Phone call state', 'BIKE_RIDE': 'Bike ride', 'UNKNOWN': 'Unknown activity'}


def duration_activity(question):
    text = question.strip().lower().rstrip('?.!')
    if re.search(r'\b(remind|save|create|delete|why|compare)\b', text):
        return None
    if not re.search(r'\b(how (?:much time|long)|total (?:time|duration)|time spent)\b', text):
        return None
    for pattern, activity in [(r'\b(walk|walked|walking)\b', 'WALKING'),
                              (r'\b(run|ran|running)\b', 'RUNNING'),
                              (r'\b(cycling|cycled)\b', 'ON_BICYCLE'),
                              (r'\b(driving|vehicle travel)\b', 'IN_VEHICLE')]:
        if re.search(pattern, text):
            return activity
    return None


def is_simple_activity_recap(question):
    text = re.sub(r'[?.!]+$', '', question.strip().lower()).strip()
    return bool(re.fullmatch(
        r'(?:please\s+)?(?:what i (?:did|have done)|what (?:did|have) i (?:do|done)|'
        r'(?:summarize|show|report|recap)(?:\s+me)?\s+(?:my\s+)?(?:activities|activity|day)|'
        r'my (?:activity|activities)(?: report| recap)?)\s+'
        r'(?:(?:in|for|over|during)\s+)?(?:the\s+)?(?:today|yesterday|last\s+\d+\s+(?:minutes?|hours?|days?))', text))


def activity_report_from_tools(question, messages, requested_at=None):
    activity = duration_activity(question)
    if not is_simple_activity_recap(question) and not activity:
        return None
    try:
        expected = prefetch_history_window(question, utc_time(requested_at) if requested_at else None)
        if not expected and not activity:
            return None
        for message in reversed(messages):
            if getattr(message, 'name', None) != 'recall_context_history':
                continue
            data = json.loads(message.content)
            start, end = utc_time(data['window_start']), utc_time(data['window_end'])
            if not isinstance(data.get('timeline'), list):
                continue
            if expected and (abs((start - expected[0]).total_seconds()) > 60 or abs((end - expected[1]).total_seconds()) > 120):
                continue
            if activity:
                return render_activity_duration(data, activity, start, end)
            if data.get('session_history_truncated', data.get('truncated', False)):
                continue
            return render_activity_report(data, start, end)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return None


def render_activity_duration(data, activity, start, end):
    from .activity_sessions import activity_totals
    window = f'{start.astimezone(IST):%d %b %H:%M}–{end.astimezone(IST):%d %b %H:%M} IST'
    if data.get('session_history_truncated', data.get('truncated', False)):
        return f'Activity history · {window}\nThe history is incomplete, so I cannot give a reliable total. Missing history is not zero activity.'
    totals = data.get('activity_totals') or activity_totals(data.get('micromoments', []), start, end)
    row = totals.get(activity, {})
    def duration(seconds):
        seconds = round(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return (f'{hours}h ' if hours else '') + f'{minutes}m {seconds}s'
    lines = [f'Activity history · {window}']
    if not row.get('session_count'):
        lines.append(f'No {ACTIVITIES[activity].lower()} was recorded in this window. Unrecorded time is not counted as inactivity.')
    else:
        if row.get('uncertain_seconds'):
            supported = max(0, row['classified_span_seconds'] - row['uncertain_seconds'])
            lines.append(f"{ACTIVITIES[activity]}: {duration(supported)} recorded across {row['session_count']} sessions.")
            lines.append(f"Session spans: {duration(row['classified_span_seconds'])}. Recording gaps: {duration(row['uncertain_seconds'])}, excluded from the activity total.")
        else:
            lines.append(f"{ACTIVITIES[activity]}: {duration(row['classified_span_seconds'])} recorded across {row['session_count']} sessions.")
        if row.get('open_sessions'):
            lines.append(f"{row['open_sessions']} sessions have no recorded end; counted only through their last observation.")
    if activity in {'WALKING', 'RUNNING'} and totals.get('ON_FOOT', {}).get('session_count'):
        foot = totals['ON_FOOT']
        lines.append(f"Separately: {duration(foot['classified_span_seconds'])} classified only as on foot; not added to {ACTIVITIES[activity].lower()}.")
    return '\n'.join(lines)


def _merge_gaps(gaps, start, end):
    intervals = sorted((max(start, utc_time(g['from'])), min(end, utc_time(g['to']))) for g in gaps)
    merged = []
    for left, right in intervals:
        if right <= left:
            continue
        if merged and left < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged


def _recorded_spans(moment, first, last):
    """Keep confident observations; do not bridge a session's coverage gaps."""
    if moment.get('evidence_status') == 'user_reported':
        return [(first, last)]
    if moment.get('coverage_status') != 'uncertain' and not moment.get('coverage_gaps'):
        return [(first, last)]
    points = sorted({utc_time(o['timestamp']) for o in moment.get('observations', [])
                     if o.get('timestamp') and first <= utc_time(o['timestamp']) <= last})
    gaps = _merge_gaps(moment.get('coverage_gaps', []), first, last)
    spans = []
    for at in points:
        # Missing coverage metadata must not turn an uncertain legacy span into
        # a continuous claim. Preserve its individual recorded observations.
        if (spans and moment.get('coverage_gaps') and (at - spans[-1][1]).total_seconds() <= 600
                and not any(left < at and right > spans[-1][1] for left, right in gaps)):
            spans[-1] = (spans[-1][0], at)
        else:
            spans.append((at, at))
    return spans


def render_activity_report(data, start, end):
    local_start, local_end = start.astimezone(IST), end.astimezone(IST)
    title = f"Observed activity · {local_start:%d %b %Y}"
    window = f"{local_start:%H:%M}–{local_end:%H:%M} IST"
    if local_end.date() != local_start.date():
        window = f"{local_start:%d %b, %H:%M}–{local_end:%d %b, %H:%M} IST"
    lines = [title, window, '']
    if not data.get('observation_count') and not any(m.get('evidence_status') == 'user_reported' for m in data.get('micromoments', [])):
        return '\n'.join(lines + ['No activity observations were recorded for this window. That does not mean you were inactive.'])

    def stamp(first, last):
        a, b = first.astimezone(IST), last.astimezone(IST)
        fmt = '%d %b %H:%M' if a.date() != b.date() or a.date() != local_start.date() else '%H:%M'
        if first != last and a.strftime(fmt) == b.strftime(fmt):
            fmt += ':%S'
        return a.strftime(fmt) if first == last else f'{a.strftime(fmt)}–{b.strftime(fmt)}'

    rows = []
    gaps = list(data.get('unobserved_gaps_over_10_minutes') or [])
    for moment in data.get('micromoments') or []:
        first = max(start, utc_time(moment.get('window_start_at') or moment['start_at']))
        last = min(end, utc_time(moment.get('window_end_at') or moment.get('end_at') or moment['last_observed_at']))
        reported = moment.get('evidence_status') == 'user_reported'
        if not reported:
            gaps.extend(moment.get('coverage_gaps') or [])
        if utc_time(moment['start_at']) < start and not reported:
            observed = [utc_time(o['timestamp']) for o in moment.get('observations', [])
                        if o.get('timestamp') and start <= utc_time(o['timestamp']) <= end]
            if not observed:
                continue
            first = min(observed)
        if last < first:
            continue
        spans = _recorded_spans(moment, first, last)
        if not spans:
            # A legacy session can lack the observations needed to localize its
            # gaps. Describe its bounds explicitly rather than invent coverage.
            rows.append((first, f"• {ACTIVITIES.get(moment.get('activity'), 'Activity')} recorded within {stamp(first, last)}; exact timing unavailable."))
            continue
        activity = ACTIVITIES.get(moment.get('activity'), 'Unknown activity')
        if moment.get('activity') == 'STILL':
            activity = 'Stationary' if reported else 'Phone stationary'
        label = 'reported by you' if reported else 'detected'
        times = ', '.join(stamp(a, b) for a, b in spans)
        line = f"• {times}: {activity} — {label}"
        if not moment.get('end_at'):
            line += f"; last recorded at {stamp(spans[-1][1], spans[-1][1])}"
        rows.append((spans[0][0], line))
    if not data.get('micromoments'):
        for episode in data.get('timeline') or []:
            first = max(start, utc_time(episode['first_observed_at']))
            last = min(end, utc_time(episode['last_observed_at']))
            if last < first:
                continue
            activity = ACTIVITIES.get(episode.get('activity'), 'Unknown activity')
            label = 'Phone stationary' if episode.get('activity') == 'STILL' else activity
            line = f'• {stamp(first, last)}: {label} — detected'
            places = episode.get('saved_place_matches') or []
            if places:
                line += '; saved-place match: ' + ', '.join(str(name)[:100] for name in places[:3])
            rows.append((first, line))
    lines.extend(line for _, line in sorted(rows, key=lambda row: row[0]))
    if not rows:
        lines.append('No activity could be identified from the available records.')
    merged = _merge_gaps(gaps, start, end)
    if merged:
        long_gaps = [(a, b) for a, b in merged if (b - a).total_seconds() >= 600]
        if long_gaps:
            lines.extend(['', 'Recording gaps — activity between readings is not established:'])
            lines.extend(f'• {stamp(a, b)} IST' for a, b in long_gaps)
        short_count = len(merged) - len(long_gaps)
        if short_count:
            lines.append(f'Also excluded: {short_count} brief gaps between the listed readings (each under 10 minutes).')
    omitted = data.get('gap_count', 0) - len(data.get('unobserved_gaps_over_10_minutes') or [])
    if omitted > 0:
        lines.append(f'Additional recording gaps: {omitted}')
    return '\n'.join(lines)
