from datetime import timedelta
from unittest.mock import Mock

from test_activity_sessions import BASE, event
from src.backend.activity_evidence import qualified_records
from src.backend.activity_sessions import build_activity_sessions, complete_window_records, activity_totals
from src.backend.activity_report import activity_report_from_tools
from langchain_core.messages import ToolMessage
import json


def sample(minute, activity, uncertain=False):
    record = event(minute, activity, kind='ACTIVITY_SAMPLE')
    if uncertain:
        record.update(activity='UNKNOWN', activity_evidence='uncertain_sample', reported_activity=activity)
    return record


def test_uncertainty_preserves_matched_session_with_separate_coverage():
    records = [event(0, 'WALKING'), sample(.1, 'UNKNOWN', True), event(1, 'WALKING', 'EXIT')]
    walk, = build_activity_sessions(records)['micromoments']
    assert walk['end_evidence'] == 'detected_exit'
    assert walk['classified_span_seconds'] == 60
    assert walk['uncertain_seconds'] == 60
    assert len(walk['event_ids']) == 3


def test_generic_foot_samples_do_not_destroy_a_walking_pair():
    records = [event(0, 'WALKING'), sample(1, 'ON_FOOT'), event(2, 'WALKING', 'EXIT')]
    qualified = qualified_records(records)
    assert qualified[-1]['activity_evidence'] != 'unpaired_exit'
    assert qualified_records(qualified) == qualified
    walk, = build_activity_sessions(records)['micromoments']
    assert walk['activity'] == 'WALKING' and walk['classified_span_seconds'] == 120
    assert walk['observations'][1]['activity'] == 'ON_FOOT'


def test_generic_foot_without_walking_start_stays_generic():
    foot, = build_activity_sessions([sample(0, 'ON_FOOT'), sample(1, 'ON_FOOT')])['micromoments']
    assert foot['activity'] == 'ON_FOOT'


def test_diagnostics_do_not_end_extend_or_enter_activity():
    diagnostic = event(1, 'UNKNOWN', kind='TELEMETRY_PIPELINE_CHECK')
    result = build_activity_sessions([event(0, 'WALKING'), diagnostic, event(2, 'WALKING', 'EXIT')])
    walk, = result['micromoments']
    assert walk['classified_span_seconds'] == 120
    assert len(walk['observations']) == 2
    assert build_activity_sessions([diagnostic])['micromoments'] == []


def test_long_gap_retains_genuine_pair_without_claiming_observed_coverage():
    walk, = build_activity_sessions([event(0, 'WALKING'), event(25, 'WALKING', 'EXIT')])['micromoments']
    assert walk['end_evidence'] == 'detected_exit'
    assert walk['uncertain_seconds'] == 1500
    assert walk['coverage_gaps'][0]['reason'] == 'observation_gap'


def test_missing_exit_does_not_count_wall_clock_time():
    walk, = build_activity_sessions([event(0, 'WALKING'), sample(1, 'WALKING'), sample(30, 'UNKNOWN', True)])['micromoments']
    totals = activity_totals([walk], BASE, BASE + timedelta(hours=1))
    assert totals['WALKING']['classified_span_seconds'] == 60
    assert walk['end_at'] is None


def test_dense_history_is_split_and_boundary_records_deduplicated():
    records = [event(i, 'WALKING') for i in range(5)]
    fs = Mock()
    def query(uid, left, right, **kwargs):
        subset = [r for r in records if left.isoformat() <= r['timestamp'] <= right.isoformat()]
        return subset[-2:], len(subset) > 2
    fs.query_context_memory.side_effect = query
    found, truncated = complete_window_records(fs, 'u', BASE, BASE + timedelta(minutes=4))
    assert found == records and not truncated
    assert fs.query_context_memory.call_count > 1


def test_query_budget_returns_incomplete_instead_of_a_false_complete_total():
    fs = Mock()
    fs.query_context_memory.return_value = ([event(0, 'WALKING')], True)
    _, truncated = complete_window_records(fs, 'u', BASE, BASE + timedelta(hours=1), max_queries=3)
    assert truncated and fs.query_context_memory.call_count == 3


def test_duration_reply_uses_complete_sessions_even_if_timeline_preview_is_capped():
    data = {'window_start': BASE.isoformat(), 'window_end': (BASE+timedelta(minutes=30)).isoformat(),
            'timeline': [], 'truncated': True, 'session_history_truncated': False,
            'activity_totals': {'WALKING': {'session_count': 1, 'classified_span_seconds': 1500,
                                         'uncertain_seconds': 900, 'open_sessions': 0}}}
    message = ToolMessage(content=json.dumps(data), name='recall_context_history', tool_call_id='h')
    reply = activity_report_from_tools('How much time i did walking?', [message])
    assert '25m 0s' in reply and '15m 0s' in reply and 'not verified continuous' in reply
    data['session_history_truncated'] = True
    reply = activity_report_from_tools('How much time i did walking?', [ToolMessage(content=json.dumps(data),name='recall_context_history',tool_call_id='h')])
    assert 'cannot give a reliable total' in reply
