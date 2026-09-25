"""Render explicit activity recaps from verified tool evidence, without a model call."""
import json
import re
from datetime import datetime, timedelta, timezone

from .context_history import prefetch_history_window, utc_time

IST = timezone(timedelta(hours=5, minutes=30))
ACTIVITIES = {'WALKING': 'Walking', 'RUNNING': 'Running', 'STILL': 'Stationary',
              'IN_VEHICLE': 'In a vehicle', 'ON_BICYCLE': 'Cycling', 'ON_FOOT': 'On foot',
              'PHONE_CALL': 'Phone call state', 'UNKNOWN': 'Unknown activity'}


def is_simple_activity_recap(question):
    text = re.sub(r'[?.!]+$', '', question.strip().lower()).strip()
    return bool(re.fullmatch(
        r'(?:please\s+)?(?:what i (?:did|have done)|what (?:did|have) i (?:do|done)|'
        r'(?:summarize|show|report|recap)(?:\s+me)?\s+(?:my\s+)?(?:activities|activity|day)|'
        r'my (?:activity|activities)(?: report| recap)?)\s+'
        r'(?:(?:in|for|over|during)\s+)?(?:the\s+)?(?:today|yesterday|last\s+\d+\s+(?:minutes?|hours?|days?))', text))


def activity_report_from_tools(question, messages, requested_at=None):
    if not is_simple_activity_recap(question):
        return None
    try:
        expected = prefetch_history_window(question, utc_time(requested_at) if requested_at else None)
        if not expected:
            return None
        for message in reversed(messages):
            if getattr(message, 'name', None) != 'recall_context_history':
                continue
            data = json.loads(message.content)
            start, end = utc_time(data['window_start']), utc_time(data['window_end'])
            if data.get('truncated') or not isinstance(data.get('timeline'), list):
                continue
            if abs((start - expected[0]).total_seconds()) > 60 or abs((end - expected[1]).total_seconds()) > 120:
                continue
            return render_activity_report(data, start, end)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return None


def render_activity_report(data, start, end):
    local_start, local_end = start.astimezone(IST), end.astimezone(IST)
    title = f"Observed activity · {local_start:%d %b %Y}"
    window = f"{local_start:%H:%M}–{local_end:%H:%M} IST"
    if local_end.date() != local_start.date():
        window = f"{local_start:%d %b, %H:%M}–{local_end:%d %b, %H:%M} IST"
    lines = [title, window, '']
    if not data.get('observation_count'):
        return '\n'.join(lines + ['No activity observations were recorded for this window. That does not mean you were inactive.'])
    moments = data.get('micromoments') or []
    rows = []
    if moments:
        for moment in moments:
            first = max(start, utc_time(moment.get('window_start_at') or moment['start_at']))
            last = min(end, utc_time(moment.get('window_end_at') or moment.get('end_at') or moment['last_observed_at']))
            # A state carried from yesterday is not an observation at midnight.
            if utc_time(moment['start_at']) < start:
                observed = [utc_time(o['timestamp']) for o in moment.get('observations', [])
                            if o.get('timestamp') and start <= utc_time(o['timestamp']) <= end]
                if not observed:
                    continue
                first = min(observed)
            if last < first:
                continue
            rows.append((first, last, moment.get('activity', 'UNKNOWN'), not moment.get('end_at'), []))
    else:
        for episode in data['timeline']:
            first = max(start, utc_time(episode['first_observed_at']))
            last = min(end, utc_time(episode['last_observed_at']))
            if last >= first:
                rows.append((first, last, episode.get('activity', 'UNKNOWN'), False, episode.get('saved_place_matches') or []))
    for first, last, activity, ongoing, places in sorted(rows):
        a, b = first.astimezone(IST), last.astimezone(IST)
        stamp = f'{a:%H:%M}' if first == last else f'{a:%H:%M}–{b:%H:%M}'
        if a.date() != b.date() or a.date() != local_start.date():
            stamp = f'{a:%d %b %H:%M}–{b:%d %b %H:%M}'
        line = f"• {stamp}: {ACTIVITIES.get(activity, 'Unknown activity')} detected"
        if ongoing:
            line += ' (last observation; no ending recorded)'
        if places:
            line += '; saved-place match: ' + ', '.join(str(name)[:100] for name in places[:3])
        lines.append(line)
    if not rows:
        lines.append('Records exist, but no reliable activity intervals could be reconstructed.')
    gaps = data.get('unobserved_gaps_over_10_minutes') or []
    if gaps:
        lines.extend(['', 'No observations were recorded in these periods:'])
        for gap in gaps:
            a, b = utc_time(gap['from']).astimezone(IST), utc_time(gap['to']).astimezone(IST)
            if a.date() != b.date() or a.date() != local_start.date():
                lines.append(f'• {a:%d %b %H:%M}–{b:%d %b %H:%M} IST')
            else:
                lines.append(f'• {a:%H:%M}–{b:%H:%M} IST')
        if data.get('gap_count', len(gaps)) > len(gaps):
            lines.append(f"Additional gaps: {data['gap_count'] - len(gaps)}")
    lines.extend(['', 'Based on recorded phone activity events. Intervals follow recorded states and can include unobserved periods or miss brief actions. Stationary does not prove sleeping or working; phone call state does not prove speaking.'])
    return '\n'.join(lines)
