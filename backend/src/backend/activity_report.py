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
        lines.append(f'No {ACTIVITIES[activity].lower()} sessions were classified in this window. This does not establish that you did none.')
    else:
        if row.get('uncertain_seconds'):
            supported = max(0, row['classified_span_seconds'] - row['uncertain_seconds'])
            lines.append(f"{ACTIVITIES[activity]}: {duration(supported)} in intervals supported by recorded classifications, across {row['session_count']} sessions.")
            lines.append(f"The full session spans cover {duration(row['classified_span_seconds'])}; {duration(row['uncertain_seconds'])} has uncertain or missing motion evidence and is excluded from that total. These are not verified continuous activity durations.")
        else:
            lines.append(f"{ACTIVITIES[activity]}: {duration(row['classified_span_seconds'])} across {row['session_count']} phone-classified sessions.")
        if row.get('open_sessions'):
            lines.append(f"{row['open_sessions']} sessions have no recorded end; counted only through their last observation.")
    if activity in {'WALKING', 'RUNNING'} and totals.get('ON_FOOT', {}).get('session_count'):
        foot = totals['ON_FOOT']
        lines.append(f"Separately: {duration(foot['classified_span_seconds'])} classified only as on foot; not added to {ACTIVITIES[activity].lower()}.")
    lines.append('Phone classifications can be wrong. Unobserved periods and gaps are unknown.')
    return '\n'.join(lines)


def render_activity_report(data, start, end):
    local_start, local_end = start.astimezone(IST), end.astimezone(IST)
    title = f"Observed activity · {local_start:%d %b %Y}"
    window = f"{local_start:%H:%M}–{local_end:%H:%M} IST"
    if local_end.date() != local_start.date():
        window = f"{local_start:%d %b, %H:%M}–{local_end:%d %b, %H:%M} IST"
    lines = [title, window, '']
    if not data.get('observation_count') and not any(m.get('evidence_status') == 'user_reported' for m in data.get('micromoments', [])):
        return '\n'.join(lines + ['No activity observations were recorded for this window. That does not mean you were inactive.'])
    moments = data.get('micromoments') or []
    rows = []
    if moments:
        for moment in moments:
            first = max(start, utc_time(moment.get('window_start_at') or moment['start_at']))
            last = min(end, utc_time(moment.get('window_end_at') or moment.get('end_at') or moment['last_observed_at']))
            # A state carried from yesterday is not an observation at midnight.
            if utc_time(moment['start_at']) < start and moment.get('evidence_status') != 'user_reported':
                observed = [utc_time(o['timestamp']) for o in moment.get('observations', [])
                            if o.get('timestamp') and start <= utc_time(o['timestamp']) <= end]
                if not observed:
                    continue
                first = min(observed)
            if last < first:
                continue
            rows.append((first, last, moment.get('activity', 'UNKNOWN'), not moment.get('end_at'), [], moment.get('evidence_status'), moment.get('coverage_status') == 'uncertain'))
    else:
        for episode in data['timeline']:
            first = max(start, utc_time(episode['first_observed_at']))
            last = min(end, utc_time(episode['last_observed_at']))
            if last >= first:
                rows.append((first, last, episode.get('activity', 'UNKNOWN'), False, episode.get('saved_place_matches') or [], None, False))
    for first, last, activity, ongoing, places, evidence, uncertain in sorted(rows, key=lambda row: row[0]):
        a, b = first.astimezone(IST), last.astimezone(IST)
        stamp = f'{a:%H:%M}' if first == last else f'{a:%H:%M}–{b:%H:%M}'
        if a.date() != b.date() or a.date() != local_start.date():
            stamp = f'{a:%d %b %H:%M}–{b:%d %b %H:%M}'
        label = 'reported by you' if evidence == 'user_reported' else 'phone classification'
        line = f"• {stamp}: {ACTIVITIES.get(activity, 'Unknown activity')} — {label}"
        if ongoing:
            line += ' (last observation; no ending recorded)'
        if uncertain:
            line += '; includes uncertain or missing evidence'
        if places:
            line += '; saved-place match: ' + ', '.join(str(name)[:100] for name in places[:3])
        lines.append(line)
    if not rows:
        lines.append('Records exist, but no reliable activity intervals could be reconstructed.')
    gaps = data.get('unobserved_gaps_over_10_minutes') or []
    if gaps:
        lines.extend(['', 'No phone observations were recorded in these periods:'])
        for gap in gaps:
            a, b = utc_time(gap['from']).astimezone(IST), utc_time(gap['to']).astimezone(IST)
            if a.date() != b.date() or a.date() != local_start.date():
                lines.append(f'• {a:%d %b %H:%M}–{b:%d %b %H:%M} IST')
            else:
                lines.append(f'• {a:%H:%M}–{b:%H:%M} IST')
        if data.get('gap_count', len(gaps)) > len(gaps):
            lines.append(f"Additional gaps: {data['gap_count'] - len(gaps)}")
    lines.extend(['', 'Phone classifications can be wrong; they do not override your account of what you did. Gaps are unknown. Stationary does not prove sleeping or working; phone call state does not prove speaking.'])
    return '\n'.join(lines)
