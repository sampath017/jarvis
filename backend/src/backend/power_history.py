"""Explicit phone switch evidence explains missing coverage, never user activity."""
from .context_history import utc_time


def off_periods(records, start, end):
    periods = []
    for record in records:
        if record.get('event_type') != 'JARVIS_OFF_INTERVAL' or record.get('source') != 'phone_power_switch':
            continue
        try:
            off = utc_time(record['power_off_at'])
            on = utc_time(record['power_on_at']) if record.get('power_on_at') else end
        except (KeyError, TypeError, ValueError):
            continue
        left, right = max(start, off), min(end, on)
        if left >= right:
            continue
        periods.append({'from': left.isoformat(), 'to': right.isoformat(),
                        'duration_seconds': (right - left).total_seconds(),
                        'reason': 'jarvis_powered_off', 'source': 'phone_power_switch',
                        'turned_off_at': off.isoformat(),
                        'turned_on_at': on.isoformat() if record.get('power_on_at') else None})
    return sorted(periods, key=lambda period: period['from'])


def unexplained_gaps(gaps, periods):
    result = []
    for gap in gaps:
        pieces = [(utc_time(gap['from']), utc_time(gap['to']))]
        for period in periods:
            off, on = utc_time(period['from']), utc_time(period['to'])
            remaining = []
            for left, right in pieces:
                if on <= left or off >= right:
                    remaining.append((left, right))
                else:
                    if left < off:
                        remaining.append((left, off))
                    if on < right:
                        remaining.append((on, right))
            pieces = remaining
        result.extend({'from': left.isoformat(), 'to': right.isoformat()}
                      for left, right in pieces if (right-left).total_seconds() > 600)
    return result
