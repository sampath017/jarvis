from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from src.backend.command_execution import CommandExecution, execution
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode, ROUTINE_WRITE_TOOLS
from src.services.database import DatabaseService


def run_tool(monkeypatch, tmp_path, name, decision='approved'):
    action = Mock()
    action.name = name
    action.invoke.return_value = 'Saved. ID: record-1'
    dispatch = Mock(return_value={'status': decision})
    context = CommandExecution(lambda _: None, approval_dispatch=dispatch)
    monkeypatch.setattr('src.graph.nodes.tier2_tools_node.build_tier2_tools', lambda *_: [action])
    token = execution.set(context)
    try:
        result = Tier2ToolsNode(DatabaseService(tmp_path / 'writes.db'))({
            'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[
                {'name': name, 'args': {'name': 'Gym'}, 'id': 'a'},
                {'name': name, 'args': {'name': 'Gym'}, 'id': 'b'},
            ])]})
    finally:
        execution.reset(token)
    return action, dispatch, context, result


@pytest.mark.parametrize('name', sorted(ROUTINE_WRITE_TOOLS))
def test_requested_routine_write_executes_once_without_approval(monkeypatch, tmp_path, name):
    action, dispatch, context, result = run_tool(monkeypatch, tmp_path, name)
    dispatch.assert_not_called()
    action.invoke.assert_called_once()
    assert context.changed_records == ['record-1']
    assert [m.content for m in result['agent_messages'][-2:]] == ['Saved. ID: record-1'] * 2


@pytest.mark.parametrize('name', ['delete_note', 'delete_task', 'delete_place',
                                 'delete_all_notes', 'delete_all_reminders',
                                 'consolidate_reminders', 'save_unknown_external_resource'])
@pytest.mark.parametrize('decision', ['approved', 'declined'])
def test_critical_or_unknown_write_requires_approval(monkeypatch, tmp_path, name, decision):
    action, dispatch, context, result = run_tool(monkeypatch, tmp_path, name, decision)
    dispatch.assert_called_once_with({'tool': name, 'arguments': {'name': 'Gym'}})
    if decision == 'approved':
        action.invoke.assert_called_once()
        assert context.changed_records == ['record-1']
    else:
        action.invoke.assert_not_called()
        assert not context.changed_records
        assert 'Not executed' in result['agent_messages'][-1].content


def test_real_gym_save_persists_without_approval(tmp_path):
    db = DatabaseService(tmp_path / 'gym.db')
    dispatch = Mock(side_effect=AssertionError('A routine place save must not prompt'))
    context = CommandExecution(lambda _: None, approval_dispatch=dispatch)
    token = execution.set(context)
    try:
        result = Tier2ToolsNode(db)({'uid': 'test-gym', 'agent_messages': [
            AIMessage(content='', tool_calls=[{'name': 'save_place',
                'args': {'name': 'Gym', 'category': 'gym', 'latitude': 12.83, 'longitude': 80.22},
                'id': 'gym'}])]})
    finally:
        execution.reset(token)
    assert 'Successfully saved place' in result['agent_messages'][-1].content
    places = db.list_places('test-gym')
    assert len(places) == 1 and places[0]['name'] == 'Gym'
    assert places[0]['latitude'] == 12.83 and places[0]['longitude'] == 80.22
    assert places[0]['id'] in context.changed_records
    dispatch.assert_not_called()
