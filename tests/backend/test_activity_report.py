import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.backend.activity_report import activity_report_from_tools, is_simple_activity_recap
from src.backend.command_execution import CommandExecution, CommandStopped, execution
from src.graph.nodes.agent import AgentNode

REQUESTED = '2026-10-05T07:47:04Z'
HISTORY = {'window_start': '2026-10-04T18:30:00Z', 'window_end': REQUESTED,
           'observation_count': 3, 'truncated': False,
           'timeline': [{'first_observed_at': '2026-10-05T01:00:00Z', 'last_observed_at': '2026-10-05T01:15:00Z', 'activity': 'WALKING', 'saved_place_matches': []}],
           'micromoments': [{'start_at': '2026-10-05T01:00:00Z', 'end_at': '2026-10-05T01:20:00Z', 'last_observed_at': '2026-10-05T01:15:00Z', 'activity': 'WALKING'},
                            {'start_at': '2026-10-05T01:20:00Z', 'end_at': None, 'last_observed_at': '2026-10-05T01:30:00Z', 'activity': 'STILL'}],
           'gap_count': 1, 'unobserved_gaps_over_10_minutes': [{'from': '2026-10-05T01:30:00Z', 'to': REQUESTED}]}


def tool(data=HISTORY):
    return ToolMessage(content=json.dumps(data), name='recall_context_history', tool_call_id='history')


def test_explicit_recap_preserves_intervals_ist_and_unknown_periods():
    report = activity_report_from_tools('What I did today', [tool()], REQUESTED)
    assert '05 Oct 2026' in report and '00:00–13:17' in report
    assert 'IST' not in report
    assert '06:30–06:50: Walking — detected' in report
    assert '06:50–07:00: Phone stationary — detected; last recorded at 07:00' in report
    assert '07:00–13:17' in report and 'Recording gaps' in report


@pytest.mark.parametrize('question', ['What did I do today and why?', 'Compare today and yesterday', 'What does my resume say?', 'Save a note about what I did today'])
def test_complex_or_write_requests_still_use_agent(question):
    assert not is_simple_activity_recap(question)
    assert activity_report_from_tools(question, [tool()], REQUESTED) is None


@pytest.mark.parametrize('change', [{'truncated': True}, {'window_start': '2026-10-03T18:30:00Z'}, {'window_end': '2026-10-05T01:30:00Z'}])
def test_incomplete_or_wrong_window_does_not_claim_complete_report(change):
    assert activity_report_from_tools('What I did today', [tool({**HISTORY, **change})], REQUESTED) is None


def test_existing_history_returns_to_model_for_synthesis(monkeypatch):
    agent = AgentNode.__new__(AgentNode)
    agent.llm = Mock()
    model = Mock()
    model.invoke.return_value = AIMessage(content='Observed activity, formatted as requested.')
    guard = Mock()
    monkeypatch.setattr('src.graph.nodes.agent.TokenBudgetGuard', lambda: guard)
    result = agent._invoke_complete('u', [HumanMessage(content='What I did today'), tool()], model,
                                    recap_question='What I did today', requested_at=REQUESTED)
    assert result.content == 'Observed activity, formatted as requested.'
    model.invoke.assert_called_once()
    assert isinstance(model.invoke.call_args.args[0][-1], ToolMessage)
    guard.record_llm_usage.assert_called_once()


def test_cancelled_request_does_not_return_report():
    token = execution.set(CommandExecution(lambda _: None, cancelled=lambda: True))
    try:
        agent = AgentNode.__new__(AgentNode)
        with pytest.raises(CommandStopped, match='Stopped at your request'):
            agent._invoke_complete('u', [tool()], Mock(), recap_question='What I did today', requested_at=REQUESTED)
    finally:
        execution.reset(token)


def test_empty_history_reports_missing_records_not_inactivity():
    data = {**HISTORY, 'observation_count': 0, 'timeline': [], 'micromoments': []}
    report = activity_report_from_tools('What I did today', [tool(data)], REQUESTED)
    assert 'No activity observations' in report and 'does not mean you were inactive' in report


def test_state_carried_from_yesterday_does_not_invent_midnight_observation():
    carried = {'start_at': '2026-10-04T10:00:00Z', 'end_at': None,
               'last_observed_at': '2026-10-05T01:30:00Z', 'activity': 'STILL',
               'observations': [{'timestamp': '2026-10-05T01:00:00Z'}, {'timestamp': '2026-10-05T01:30:00Z'}]}
    report = activity_report_from_tools('What I did today', [tool({**HISTORY, 'micromoments': [carried]})], REQUESTED)
    assert '06:30–07:00: Phone stationary — detected' in report
    assert '00:00–07:00: Phone stationary' not in report


def test_movement_evidence_finishes_through_actual_agent_model(monkeypatch, tmp_path):
    from src.services.database import DatabaseService
    db = DatabaseService(tmp_path / 'report.db')
    agent = AgentNode.__new__(AgentNode)
    agent.db = db
    agent.llm = Mock()
    agent.llm.bind_tools.return_value.invoke.return_value = AIMessage(content='Observed activity in the requested format.')
    monkeypatch.setattr('src.graph.nodes.agent.TokenBudgetGuard', Mock)
    monkeypatch.setattr('src.graph.nodes.agent.build_agent_tools', lambda *_: [])
    result = agent({'uid': 'report-test', 'request_type': 'USER_COMMAND',
        'user_command': 'What I did today', 'agent_step_count': 1,
        'raw_request': {'text': 'What I did today', 'timestamp': REQUESTED},
        'agent_messages': [HumanMessage(content='What I did today'),
            AIMessage(content='', tool_calls=[{'name': 'recall_context_history', 'args': {}, 'id': 'history'}]), tool()]})
    assert result['user_response'].startswith('Observed activity')
    assert result['agent_messages'][-1].tool_calls == []
    agent.llm.bind_tools.return_value.invoke.assert_called_once()


def test_strong_activity_is_not_labelled_uncertain_because_of_a_later_gap():
    moment = {'start_at': '2026-10-05T01:00:00Z', 'end_at': '2026-10-05T02:00:00Z',
              'last_observed_at': '2026-10-05T02:00:00Z', 'activity': 'IN_VEHICLE',
              'coverage_status': 'uncertain',
              'coverage_gaps': [{'from': '2026-10-05T01:15:00Z', 'to': '2026-10-05T01:55:00Z'}],
              'observations': [{'timestamp': t, 'activity_confidence': 97} for t in
                  ['2026-10-05T01:00:00Z', '2026-10-05T01:05:00Z', '2026-10-05T01:15:00Z',
                   '2026-10-05T01:55:00Z', '2026-10-05T02:00:00Z']]}
    report = activity_report_from_tools('What I did today', [tool({**HISTORY, 'micromoments': [moment], 'unobserved_gaps_over_10_minutes': [], 'gap_count': 0})], REQUESTED)
    assert '06:30–06:45, 07:25–07:30: In a vehicle — detected' in report
    assert '06:45–07:25' in report
    assert '06:30–07:30: In a vehicle' not in report
    assert 'includes uncertain' not in report
    assert 'Phone classifications can be wrong' not in report


def test_isolated_readings_survive_gaps_without_inventing_continuity():
    moment = {'start_at': '2026-10-05T01:00:00Z', 'end_at': None,
              'last_observed_at': '2026-10-05T03:00:00Z', 'activity': 'STILL',
              'coverage_status': 'uncertain',
              'coverage_gaps': [{'from': '2026-10-05T01:00:00Z', 'to': '2026-10-05T03:00:00Z'}],
              'observations': [{'timestamp': '2026-10-05T01:00:00Z'}, {'timestamp': '2026-10-05T03:00:00Z'}]}
    report = activity_report_from_tools('What I did today', [tool({**HISTORY, 'micromoments': [moment]})], REQUESTED)
    assert '06:30, 08:30: Phone stationary — detected' in report
    assert '06:30–08:30: Phone stationary' not in report
    assert 'sleep' not in report.lower()


def test_user_report_is_preserved_even_when_phone_coverage_is_missing():
    moment = {'start_at': '2026-10-05T01:00:00Z', 'end_at': '2026-10-05T02:00:00Z',
              'activity': 'WALKING', 'evidence_status': 'user_reported'}
    report = activity_report_from_tools('What I did today', [tool({**HISTORY, 'micromoments': [moment]})], REQUESTED)
    assert '06:30–07:30: Walking — reported by you' in report


def test_duration_excludes_gaps_without_blanket_disclaimer():
    data = {**HISTORY, 'activity_totals': {'WALKING': {'session_count': 1,
            'classified_span_seconds': 1200, 'uncertain_seconds': 300, 'open_sessions': 0}}}
    report = activity_report_from_tools('How long did I walk today?', [tool(data)], REQUESTED)
    assert 'Walking: 15m 0s recorded across 1 sessions.' in report
    assert '5m 0s' in report and 'excluded' in report
    assert 'Phone classifications can be wrong' not in report
