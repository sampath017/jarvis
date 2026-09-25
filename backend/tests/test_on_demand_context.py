from unittest.mock import Mock
from langchain_core.messages import AIMessage
from src.backend.command_execution import CommandExecution, execution
from src.cloud.tier2_agent_tools import build_tier2_tools
from src.graph.nodes.load_context import LoadContextNode
from src.graph.nodes.tier2_agent import Tier2AgentNode
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.services.database import DatabaseService


def test_resume_followup_reuses_chat_without_personal_context_reads(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'routing.db')
    cloud = Mock(side_effect=AssertionError('Unrelated cloud context must not be loaded'))
    monkeypatch.setattr('src.services.firestore_service.FirestoreService', cloud)
    monkeypatch.setattr(db, 'load_scoped_context', Mock(side_effect=AssertionError('No broad context reads')))
    monkeypatch.setattr(db, 'get_latest_gps', Mock(side_effect=AssertionError('No location reads')))
    history = [{'role': 'assistant', 'content': 'The resume lists Jan 2020–Jan 2022 and Jan 2023–Jan 2025.'}]
    state = {'uid': 'u', 'request_type': 'USER_COMMAND', 'raw_request': {'text': 'Experience in years?', 'history': history}}
    result = LoadContextNode(db)(state)
    assert result['messages'] == history and result['context_scope'] == 'on_demand'
    prompt = Tier2AgentNode(db)._build_user_prompt({**state, **result})
    assert 'Experience in years?' in prompt
    assert 'Existing Active Reminders' not in prompt and 'Internal GPS Reference' not in prompt
    cloud.assert_not_called()


def test_current_location_tool_requests_phone_only_when_invoked(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'location.db')
    dispatch = Mock(return_value={'status': 'unavailable'})
    monkeypatch.setattr(db, 'get_latest_gps', Mock(side_effect=AssertionError('Do not use stale location')))
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch))
    try:
        tools = {tool.name: tool for tool in build_tier2_tools(db, 'u')}
        dispatch.assert_not_called()
        assert 'unavailable' in tools['get_current_location'].invoke({})
        dispatch.assert_called_once_with({'operation': 'location_read'})
    finally:
        execution.reset(token)


def test_successful_phone_location_is_saved_and_resolved(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'fresh-location.db')
    observed = '2026-10-07T06:48:00+00:00'
    dispatch = Mock(return_value={'status': 'ok', 'gps': {
        'latitude': 12.8, 'longitude': 80.2, 'accuracy': 12.0,
    }, 'observed_at': observed})
    monkeypatch.setattr('src.services.places_client.PlacesClient.search_nearby', Mock(return_value=[]))
    monkeypatch.setattr('src.graph.nodes.tier2_agent.reverse_geocode_location', Mock(return_value='Test address'))
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch))
    try:
        tools = {tool.name: tool for tool in build_tier2_tools(db, 'u')}
        answer = tools['get_current_location'].invoke({})
        assert 'Area / Address: Test address' in answer
        saved = db.get_latest_gps('u')
        assert saved['latitude'] == 12.8
        assert saved['longitude'] == 80.2
        assert saved['accuracy_m'] == 12.0
        assert saved['observed_at'] == observed
        dispatch.assert_called_once_with({'operation': 'location_read'})
    finally:
        execution.reset(token)


def test_explicit_file_save_uses_standing_permission_not_generic_approval(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'save.db')
    dispatch = Mock(return_value={'status': 'ok'})
    token = execution.set(CommandExecution(lambda _: None, approval_dispatch=dispatch))
    try:
        Tier2ToolsNode(db)({'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[{'name': 'save_file_to_drive', 'args': {'file_id': 'cached-id'}, 'id': 'save'}])]})
        dispatch.assert_called_once_with({'operation': 'file_save', 'file_id': 'cached-id'})
    finally:
        execution.reset(token)
