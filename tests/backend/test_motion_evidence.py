from datetime import datetime, timezone
from src.backend.activity_evidence import qualified_records
from src.backend.activity_sessions import build_activity_sessions
from src.backend.context_history import build_timeline


def event(at, activity='STILL', kind='ACTIVITY_ENTER', transition='ENTER', **extra):
    return dict(timestamp=f'2026-10-08T{at}+00:00', activity=activity,
                event_type=kind, transition=transition, event_id=at+kind, **extra)


def test_overnight_gap_does_not_become_stationary_or_walking():
    records = [event('19:00:13'), event('19:11:09', kind='CONTEXT_CHECKPOINT'),
               event('19:31:33', 'WALKING', 'ACTIVITY_EXIT', 'EXIT'), event('19:31:33'),
               event('19:35:04', kind='WIFI_CONNECTED')]
    qualified = qualified_records(records)
    assert qualified[1]['activity'] == 'UNKNOWN'
    assert qualified[2]['activity_evidence'] == 'unpaired_exit'
    assert qualified_records(qualified) == qualified
    moments = build_activity_sessions(records)['micromoments']
    assert not any(m['activity'] == 'WALKING' for m in moments)
    assert moments[0]['end_at'] == records[0]['timestamp']
    assert moments[1]['start_at'] == records[3]['timestamp']


def test_low_confidence_sample_and_cached_label_never_train_a_stop():
    records = [event('19:00:00'), event('19:01:00', kind='ACTIVITY_SAMPLE',
               activity_evidence='uncertain_sample', activity_confidence=45),
               event('19:05:00', kind='CONTEXT_CHECKPOINT'), event('19:06:00', 'WALKING')]
    analysis = build_activity_sessions(records)
    assert analysis['routine_learning']['completed_stops'] == 0
    assert analysis['micromoments'][0]['end_at'] == records[-1]['timestamp']
    assert analysis['micromoments'][0]['coverage_status'] == 'uncertain'


def test_timeline_exposes_orphan_exit_as_unknown_preserving_raw_label():
    raw = [event('19:31:33', 'WALKING', 'ACTIVITY_EXIT', 'EXIT')]
    records = qualified_records(raw)
    assert records[0]['reported_activity'] == 'WALKING'
    timeline = build_timeline(raw, datetime(2026,10,8,19,tzinfo=timezone.utc), datetime(2026,10,8,20,tzinfo=timezone.utc))
    assert timeline['timeline'][0]['activity'] == 'UNKNOWN'
    assert raw[0]['activity'] == 'WALKING'


def test_user_correction_is_labelled_as_reported_not_sensor_detected():
    records = [event('19:20:00', 'BIKE_RIDE', 'USER_REPORTED_ACTIVITY',
                     source='user_report', reported_end_at='2026-10-08T19:30:00+00:00')]
    moment = build_activity_sessions(records)['micromoments'][0]
    assert moment['activity'] == 'BIKE_RIDE'
    assert moment['evidence_status'] == 'user_reported'
    assert moment['observations'] == []
    from src.backend.activity_report import render_activity_report
    start, end = datetime(2026,10,8,19,25,tzinfo=timezone.utc), datetime(2026,10,8,19,35,tzinfo=timezone.utc)
    report = render_activity_report({'observation_count': 0, 'micromoments': [moment]}, start, end)
    assert '00:55–01:00: Bike ride — reported by you' in report
