"""Separate measured classifications from cached labels; preserve raw evidence."""
from .context_history import utc_time

CACHED_EVENTS = {"CONTEXT_CHECKPOINT", "DWELL_CHECK", "WIFI_CONNECTED", "WIFI_DISCONNECTED",
                 "BLUETOOTH_CONNECTED", "BLUETOOTH_DISCONNECTED", "BACKEND_CONTEXT_REQUEST"}
DIAGNOSTIC_EVENTS = {"TELEMETRY_PIPELINE_CHECK"}


def compatible_motion(current, observed):
    """A broad on-foot sample does not contradict an explicit walking/run label."""
    return current == observed or (current in {'WALKING', 'RUNNING'} and observed == 'ON_FOOT')


def qualified_records(records):
    result, current = [], None
    ordered = []
    for record in records:
        try:
            ordered.append((utc_time(record['timestamp']), record))
        except (KeyError, TypeError, ValueError):
            continue
    for at, original in sorted(ordered, key=lambda pair: (pair[0], pair[1].get('transition') != 'EXIT')):
        record = dict(original)
        kind = record.get('event_type')
        activity = record.get('activity', 'UNKNOWN')
        evidence = record.get('activity_evidence')
        try:
            at = utc_time(record['timestamp'])
        except (KeyError, TypeError, ValueError):
            continue
        if record.get('source') == 'user_report' and kind == 'USER_REPORTED_ACTIVITY':
            record['activity_evidence'] = 'user_reported'
        elif evidence == 'unpaired_exit':
            record['activity'] = 'UNKNOWN'
        elif kind in {'CALL_START', 'CALL_END'}:
            record['activity_evidence'] = 'phone_call_state'
        elif kind in DIAGNOSTIC_EVENTS:
            record.update(reported_activity=record.get('reported_activity') or activity,
                          activity='UNKNOWN', activity_evidence='diagnostic_event')
        elif evidence == 'cached_state' or kind in CACHED_EVENTS:
            record.update(reported_activity=record.get('reported_activity') or activity,
                          activity='UNKNOWN', activity_evidence='cached_state')
        elif kind == 'ACTIVITY_SAMPLE' and (evidence != 'repeated_android_samples' or
                                          (record.get('activity_confidence') or 0) < 80):
            record.update(reported_activity=record.get('reported_activity') or activity,
                          activity='UNKNOWN', activity_evidence='uncertain_sample')
        elif record.get('transition') == 'EXIT':
            if current != activity:
                record.update(reported_activity=record.get('reported_activity') or activity,
                              activity='UNKNOWN', activity_evidence='unpaired_exit')
            else:
                record['activity_evidence'] = evidence or 'android_transition'
                current = None
        else:
            record['activity_evidence'] = evidence or ('android_transition' if kind in {'ACTIVITY_ENTER', 'ACTIVITY_TRANSITION'} else 'legacy_observation')
            # Pair transitions independently of the noisier sampling stream.
            # In particular ON_FOOT must not erase a genuine WALKING ENTER.
            if kind in {'ACTIVITY_ENTER', 'ACTIVITY_TRANSITION'}:
                current = activity
        result.append(record)
    return result
