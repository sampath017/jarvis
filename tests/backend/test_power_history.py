from datetime import datetime, timedelta, timezone

from src.backend.context_history import build_timeline
from src.backend.activity_sessions import build_activity_sessions, enriched_history

BASE = datetime(2026, 10, 28, 8, tzinfo=timezone.utc)


def stamp(minutes):
    return (BASE + timedelta(minutes=minutes)).isoformat()


def off(start, end=None):
    return {'event_id': 'off-1', 'timestamp': stamp(max(start, 0)),
            'event_type': 'JARVIS_OFF_INTERVAL', 'source': 'phone_power_switch',
            'power_off_at': stamp(start), 'power_on_at': stamp(end) if end is not None else None}


def motion(at, transition='ENTER'):
    return {'event_id': f'motion-{at}', 'timestamp': stamp(at), 'activity': 'WALKING',
            'event_type': f'ACTIVITY_{transition}', 'transition': transition}


def test_hour_turned_off_is_explained_without_fabricating_activity():
    result = build_timeline([off(0, 60)], BASE, BASE + timedelta(hours=1))
    assert result['observation_count'] == 0
    assert result['timeline'] == []
    assert result['gap_count'] == 0
    assert result['powered_off_periods'][0]['duration_seconds'] == 3600
    assert result['powered_off_periods'][0]['reason'] == 'jarvis_powered_off'


def test_partial_gap_retains_unexplained_missing_time():
    result = build_timeline([off(20, 60)], BASE, BASE + timedelta(minutes=90))
    assert result['unobserved_gaps_over_10_minutes'] == [
        {'from': stamp(0), 'to': stamp(20)}, {'from': stamp(60), 'to': stamp(90)}]


def test_interval_started_before_window_and_ongoing_off_are_clipped():
    result = build_timeline([off(-300)], BASE, BASE + timedelta(minutes=60))
    period = result['powered_off_periods'][0]
    assert period['from'] == stamp(0)
    assert period['turned_off_at'] == stamp(-300)
    assert period['turned_on_at'] is None
    assert period['duration_seconds'] == 3600


def test_no_recorded_switch_cannot_explain_a_gap():
    result = build_timeline([], BASE, BASE + timedelta(hours=1))
    assert result['powered_off_periods'] == []
    assert result['gap_count'] == 1


def test_power_off_breaks_activity_pairing_without_inventing_exit():
    result = build_activity_sessions([motion(0), off(10, 70), motion(80, 'EXIT')])
    moments = result['micromoments']
    assert len(moments) == 1
    assert moments[0]['end_at'] == stamp(0)
    assert moments[0]['end_evidence'] == 'monitoring_powered_off'


def test_enriched_history_preserves_power_explanation_for_agent():
    class Store:
        def get_activity_routines(self, uid):
            return {}

        def query_context_memory(self, *args, **kwargs):
            return [off(0, 60)], False

    result, _ = enriched_history(Store(), 'u', BASE, BASE + timedelta(hours=1))
    assert result['powered_off_periods'][0]['duration_seconds'] == 3600
    assert result['activity_totals'] == {}
