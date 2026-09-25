import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.backend.activity_report import activity_report_from_tools, is_simple_activity_recap
from src.backend.command_execution import CommandExecution, CommandStopped, execution
from src.graph.nodes.tier2_agent import Tier2AgentNode

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
    assert '05 Oct 2026' in report and '00:00–13:17 IST' in report
    assert '06:30–06:50: Walking detected' in report
    assert '06:50–07:00: Stationary detected (last observation; no ending recorded)' in report
    assert '07:00–13:17 IST' in report and 'does not prove sleeping or working' in report


@pytest.mark.parametrize('question', ['What did I do today and why?', 'Compare today and yesterday', 'What does my resume say?', 'Save a note about what I did today'])
def test_complex_or_write_requests_still_use_agent(question):
    assert not is_simple_activity_recap(question)
    assert activity_report_from_tools(question, [tool()], REQUESTED) is None


@pytest.mark.parametrize('change', [{'truncated': True}, {'window_start': '2026-10-03T18:30:00Z'}, {'window_end': '2026-10-05T01:30:00Z'}])
def test_incomplete_or_wrong_window_does_not_claim_complete_report(change):
    assert activity_report_from_tools('What I did today', [tool({**HISTORY, **change})], REQUESTED) is None


def test_existing_history_finishes_without_model_or_token_usage(monkeypatch):
    agent = Tier2AgentNode.__new__(Tier2AgentNode)
    agent.llm = Mock()
    model = Mock(side_effect=AssertionError('Another model call is unnecessary'))
    guard = Mock()
    monkeypatch.setattr('src.graph.nodes.tier2_agent.TokenBudgetGuard', lambda: guard)
    result = agent._invoke_complete('u', [HumanMessage(content='What I did today'), tool()], model,
                                    recap_question='What I did today', requested_at=REQUESTED)
    assert result.response_metadata['evidence_report'] is True
    model.invoke.assert_not_called()
    guard.record_llm_usage.assert_not_called()


def test_cancelled_request_does_not_return_report():
    token = execution.set(CommandExecution(lambda _: None, cancelled=lambda: True))
    try:
        agent = Tier2AgentNode.__new__(Tier2AgentNode)
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
    assert '06:30–07:00: Stationary detected' in report
    assert '00:00–07:00: Stationary' not in report


def test_report_finishes_actual_agent_node_without_another_generation(monkeypatch, tmp_path):
    from src.services.database import DatabaseService
    db = DatabaseService(tmp_path / 'report.db')
    agent = Tier2AgentNode.__new__(Tier2AgentNode)
    agent.db = db
    agent.llm = Mock()
    monkeypatch.setattr('src.graph.nodes.tier2_agent.build_tier2_tools', lambda *_: [])
    result = agent({'uid': 'report-test', 'request_type': 'USER_COMMAND',
        'user_command': 'What I did today', 'agent_step_count': 1,
        'raw_request': {'text': 'What I did today', 'timestamp': REQUESTED},
        'agent_messages': [HumanMessage(content='What I did today'),
            AIMessage(content='', tool_calls=[{'name': 'recall_context_history', 'args': {}, 'id': 'history'}]), tool()]})
    assert result['user_response'].startswith('Observed activity')
    assert result['agent_messages'][-1].tool_calls == []
    agent.llm.bind_tools.return_value.invoke.assert_not_called()
