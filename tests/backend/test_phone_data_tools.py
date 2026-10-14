"""Typed phone tools, native chart contract, and the agent/tool observation loop."""
import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from src.backend.command_execution import CommandExecution, CommandStopped, execution
from src.cloud.phone_data_tools import phone_data_tools
from src.cloud.chart_tools import chart_tools
from src.cloud.agent_tools import build_agent_tools
from src.graph.nodes.agent import AgentNode, SYSTEM_PROMPT_CHAT
from src.graph.nodes.agent_tools import AgentToolsNode
from src.services.database import DatabaseService


def test_registry_exposes_distinct_sources_and_formatting(tmp_path):
    tools = {tool.name: tool for tool in build_agent_tools(DatabaseService(tmp_path / 'registry.db'), 'u')}
    assert {'get_app_usage', 'get_health_records', 'render_chart'} <= tools.keys()
    assert 'NOT movement/location' in tools['get_app_usage'].description
    assert 'movement/location' in tools['recall_context_history'].description.lower()
    assert 'get_app_usage' in tools['recall_context_history'].description
    assert 'A date phrase' in SYSTEM_PROMPT_CHAT


@pytest.mark.parametrize('name,args,operation', [
    ('get_app_usage', {'start_date': '2026-10-26', 'app_query': 'WhatsApp', 'max_apps': 12}, 'app_usage_read'),
    ('get_health_records', {'metric': 'steps', 'start_date': '2026-10-26'}, 'health_records_read'),
    ('get_health_records', {'metric': 'sleep', 'start_date': '2026-10-26'}, 'health_records_read'),
])
def test_private_dispatch_preserves_typed_arguments_without_approval(name, args, operation):
    dispatch = Mock(return_value={'status': 'permission_required', 'source': operation})
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch))
    try:
        tool = next(t for t in phone_data_tools() if t.name == name)
        result = json.loads(tool.invoke(args))
        assert result['status'] == 'permission_required'
        dispatch.assert_called_once_with({'operation': operation, 'end_date': '2026-10-26',
            **({'app_query': '', 'max_apps': 20} if name == 'get_app_usage' else {}), **args})
    finally:
        execution.reset(token)


@pytest.mark.parametrize('args', [
    {'start_date': '2026-02-30'}, {'start_date': '2999-10-27'},
    {'start_date': '2026-10-26', 'end_date': '2026-10-25'},
    {'start_date': '2026-09-26', 'end_date': '2026-10-27'},
    {'start_date': 'yesterday'}, {'start_date': '2026-10-26', 'max_apps': 0},
])
def test_invalid_window_never_dispatches(args):
    dispatch = Mock()
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch))
    try:
        assert json.loads(phone_data_tools()[0].invoke(args))['status'] == 'invalid_arguments'
        dispatch.assert_not_called()
    finally:
        execution.reset(token)


def test_unconnected_and_cancelled_reads_cannot_invent_or_substitute_data():
    tool = phone_data_tools()[0]
    result = json.loads(tool.invoke({'start_date': '2026-10-26'}))
    assert result['status'] == 'unavailable' and 'infer zero' in result['message']
    dispatch = Mock()
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch, cancelled=lambda: True))
    try:
        with pytest.raises(CommandStopped):
            tool.invoke({'start_date': '2026-10-26'})
        dispatch.assert_not_called()
    finally:
        execution.reset(token)


def chart_args(**changes):
    return {'chart_type': 'pie', 'title': 'Screen time · 26 Oct', 'unit': 'minutes',
        'labels': ['WhatsApp', 'Jarvis'], 'series': [{'name': 'Usage', 'values': [1.5, .5]}], **changes}


def test_chart_tool_retains_exact_proportions_and_renderer_schema():
    result = json.loads(chart_tools()[0].invoke(chart_args()))
    assert result['status'] == 'ok'
    assert result['chart']['series'][0]['values'] == [1.5, .5]
    assert json.loads(result['markdown'].removeprefix('```chart\n').removesuffix('\n```')) == result['chart']


@pytest.mark.parametrize('changes', [
    {'labels': []}, {'labels': ['one']}, {'title': ''},
    {'series': [{'name': 'Usage', 'values': [0, 0]}]},
    {'series': [{'name': 'Usage', 'values': [-1, 2]}]},
    {'labels': [str(i) for i in range(13)], 'series': [{'name': 'Usage', 'values': [1] * 13}]},
])
def test_invalid_chart_can_be_corrected_without_rendering(changes):
    assert json.loads(chart_tools()[0].invoke(chart_args(**changes)))['status'] == 'invalid_arguments'


@pytest.mark.parametrize('value', [True, float('inf'), float('nan'), 1e13, '1'])
def test_chart_rejects_non_numeric_nonfinite_or_unbounded_values(value):
    with pytest.raises(ValidationError):
        chart_tools()[0].invoke(chart_args(series=[{'name': 'Usage', 'values': [value, 1]}]))


def test_phone_read_and_chart_observations_return_to_model_in_order(monkeypatch, tmp_path):
    """Scripted provider verifies orchestration; live source selection is a separate probe."""
    db = DatabaseService(tmp_path / 'loop.db')
    agent = AgentNode.__new__(AgentNode)
    agent.db = db
    agent.llm = Mock()
    chart = json.loads(chart_tools()[0].invoke(chart_args()))['markdown']
    model = agent.llm.bind_tools.return_value
    model.invoke.side_effect = [
        AIMessage(content='', tool_calls=[{'name': 'get_app_usage', 'args': {'start_date': '2026-10-26', 'max_apps': 12}, 'id': 'usage'}]),
        AIMessage(content='', tool_calls=[{'name': 'render_chart', 'args': chart_args(), 'id': 'chart'}]),
        AIMessage(content=chart),
    ]
    monkeypatch.setattr('src.graph.nodes.agent.TokenBudgetGuard', Mock)
    sample = {'status': 'ok', 'source': 'android_app_usage', 'days': [{'day': '2026-10-26', 'status': 'ok',
        'total_ms': 120000, 'apps': [{'name': 'WhatsApp', 'milliseconds': 90000}, {'name': 'Jarvis', 'milliseconds': 30000}]}]}
    dispatch = Mock(return_value=sample)
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch))
    state = {'uid': 'u', 'request_type': 'USER_COMMAND', 'context_scope': 'on_demand', 'raw_request': {
        'text': 'Yesterday', 'timestamp': '2026-10-26T18:33:00Z', 'history': [
            {'role': 'user', 'content': 'Show my screen time'},
            {'role': 'assistant', 'content': 'Screen time · 27 Oct'},
            {'role': 'user', 'content': 'Give me pie chart'},
            {'role': 'assistant', 'content': 'Screen time pie chart · 27 Oct'},
        ]}}
    try:
        tools = AgentToolsNode(db)
        state.update(agent(state))
        state.update(tools(state))
        state.update(agent(state))
        state.update(tools(state))
        state.update(agent(state))
        assert state['user_response'] == chart
        observations = [m for m in state['agent_messages'] if isinstance(m, ToolMessage)]
        assert [m.name for m in observations] == ['get_app_usage', 'render_chart']
        assert json.loads(observations[0].content)['source'] == 'android_app_usage'
        assert model.invoke.call_count == 3
        dispatch.assert_called_once_with({'operation': 'app_usage_read', 'start_date': '2026-10-26',
            'end_date': '2026-10-26', 'app_query': '', 'max_apps': 12})
    finally:
        execution.reset(token)
