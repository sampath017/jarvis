"""Concurrent reads must preserve ordering, write barriers and location evidence."""
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

from langchain_core.messages import AIMessage

from src.backend.command_execution import CommandExecution, execution
from src.backend.context_history import build_timeline, prefetch_history_window
from src.graph.nodes.load_context import LoadContextNode
from src.graph.nodes.tier2_agent import Tier2AgentNode
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.services.database import DatabaseService


def test_parallel_reads_preserve_call_order_and_command_context(monkeypatch, tmp_path):
    barrier = threading.Barrier(2)
    context = CommandExecution(lambda _: None)
    def read(args):
        assert execution.get() is context
        barrier.wait(timeout=3)
        return args['value']
    tools = [Mock(name='list_notes'), Mock(name='list_tasks')]
    for t, name in zip(tools, ('list_notes', 'list_tasks')):
        t.name = name
        t.invoke.side_effect = read
    monkeypatch.setattr('src.graph.nodes.tier2_tools_node.build_tier2_tools', lambda *_: tools)
    token = execution.set(context)
    try:
        result = Tier2ToolsNode(DatabaseService(tmp_path / 'tools.db'))({
            'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[
                {'name': 'list_notes', 'args': {'value': 'first'}, 'id': 'a'},
                {'name': 'list_tasks', 'args': {'value': 'second'}, 'id': 'b'},
            ])]})
    finally:
        execution.reset(token)
    assert [m.content for m in result['agent_messages'][-2:]] == ['first', 'second']
    assert context.tools == 2


def test_write_is_a_barrier_between_read_batches(monkeypatch, tmp_path):
    order = []
    tools = []
    for name in ('list_notes', 'create_note', 'list_tasks'):
        t = Mock()
        t.name = name
        t.invoke.side_effect = lambda _, name=name: order.append(name) or name
        tools.append(t)
    monkeypatch.setattr('src.graph.nodes.tier2_tools_node.build_tier2_tools', lambda *_: tools)
    Tier2ToolsNode(DatabaseService(tmp_path / 'tools.db'))({
        'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[
            {'name': name, 'args': {}, 'id': str(i)} for i, name in enumerate(
                ('list_notes', 'create_note', 'list_tasks'))])]})
    assert order == ['list_notes', 'create_note', 'list_tasks']


def test_telemetry_cloud_reads_overlap_and_one_failure_preserves_reminders(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'context.db')
    barrier = threading.Barrier(3)
    memory = [{'timestamp': datetime.now(timezone.utc).isoformat(), 'activity': 'IN_VEHICLE'}]
    def read(value, fail=False):
        barrier.wait(timeout=3)
        if fail:
            raise RuntimeError('optional semantic read failed')
        return value
    fs = Mock(is_available=True)
    fs.get_active_mobility_session.side_effect = lambda _: read(None)
    fs.get_reminders.side_effect = lambda _: read([{'id': 'r', 'title': 'Buy water'}])
    fs.get_places.side_effect = lambda _: read([], fail=True)
    fs.get_context_memory.side_effect = lambda _, limit: read(memory)
    fs.get_semantic_contexts.side_effect = lambda _: read([], fail=True)
    monkeypatch.setattr('src.services.firestore_service.FirestoreService', lambda: fs)
    monkeypatch.setattr('src.cloud.tier2_agent_tools.is_test_environment', lambda: False)
    result = LoadContextNode(db)({'uid': 'u', 'request_type': 'CONTEXT_EVENT'})
    assert result['context_memory'] == []
    assert result['semantic_contexts'] == []
    assert result['reminders'][0]['title'] == 'Buy water'
    assert result['cloud_context_loaded'] is True
    node = Tier2AgentNode(db)
    node._build_user_prompt({**result, 'uid': 'u', 'raw_request': {'text': 'hello'}})
    fs.get_reminders.assert_called_once()
    fs.get_places.assert_called_once()


def test_chat_does_not_enrich_location_even_if_old_client_includes_gps(monkeypatch, tmp_path):
    barrier = threading.Barrier(2)
    fs = Mock(is_available=False)
    monkeypatch.setattr('src.services.firestore_service.FirestoreService', lambda: fs)
    def empty(*args, **kwargs):
        barrier.wait(timeout=3)
        return []
    def address(*args):
        barrier.wait(timeout=3)
        return ''
    places = Mock(side_effect=empty)
    geocode = Mock(side_effect=address)
    monkeypatch.setattr('src.services.places_client.PlacesClient.search_nearby', places)
    monkeypatch.setattr('src.graph.nodes.tier2_agent.reverse_geocode_location', geocode)
    db = DatabaseService(tmp_path / 'context.db')
    result = LoadContextNode(db)({'uid': 'u', 'request_type': 'USER_COMMAND',
        'raw_request': {'latitude': 12.8, 'longitude': 80.2}})
    prompt = Tier2AgentNode(db)._build_user_prompt({**result, 'uid': 'u'})
    assert 'Internal GPS Reference' not in prompt
    places.assert_not_called()
    geocode.assert_not_called()


def test_timeline_retains_each_gps_fix_without_filling_missing_locations():
    start = datetime(2026, 10, 4, 7, 40, tzinfo=timezone.utc)
    records = [
        {'timestamp': (start + timedelta(minutes=i)).isoformat(), 'activity': 'IN_VEHICLE',
         'gps': {'latitude': 12.8 + i / 100, 'longitude': 80.2, 'accuracy_m': 10} if i != 1 else None}
        for i in range(3)
    ]
    result = build_timeline(records, start, start + timedelta(minutes=4))
    assert result['observations_with_gps'] == 2
    locations = result['timeline'][0]['location_observations']
    assert len(locations) == 2
    assert locations[0]['observed_at'] == records[0]['timestamp']
    assert locations[1]['latitude'] == records[2]['gps']['latitude']


def test_model_capability_settings_are_unchanged(monkeypatch, tmp_path):
    constructor = Mock()
    monkeypatch.setattr('src.graph.nodes.tier2_agent.OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr('src.graph.nodes.tier2_agent.ChatOpenAI', constructor)
    Tier2AgentNode(DatabaseService(tmp_path / 'model.db'))
    assert 'reasoning' not in constructor.call_args.kwargs.get('extra_body', {})
    assert 'reasoning_effort' not in constructor.call_args.kwargs
    from src.settings import TIER2_OUTPUT_TOKENS
    assert constructor.call_args.kwargs['max_tokens'] == TIER2_OUTPUT_TOKENS


def test_prefetch_uses_ist_calendar_and_skips_ambiguous_requests():
    now = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)
    start, end = prefetch_history_window('What I did today', now)
    assert start == datetime(2026, 10, 3, 18, 30, tzinfo=timezone.utc)
    assert end == now
    start, end = prefetch_history_window('My activity yesterday', now)
    assert start == datetime(2026, 10, 2, 18, 30, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 3, 18, 30, tzinfo=timezone.utc)
    assert prefetch_history_window('My activity last 10 minutes', now) == (now - timedelta(minutes=10), now)
    assert prefetch_history_window('Compare my activity today and yesterday', now) is None
    assert prefetch_history_window('Remind me to walk today', now) is None
    assert prefetch_history_window('What is the weather today', now) is None


def test_history_is_requested_by_tool_instead_of_prefetched_for_all_commands(monkeypatch, tmp_path):
    fs = Mock(is_available=True)
    fs.get_active_mobility_session.return_value = None
    fs.get_reminders.return_value = []
    fs.get_places.return_value = []
    fs.get_semantic_contexts.return_value = []
    fs.get_context_memory.return_value = []
    fs.query_context_memory.return_value = ([], False)
    monkeypatch.setattr('src.services.firestore_service.FirestoreService', lambda: fs)
    monkeypatch.setattr('src.cloud.tier2_agent_tools.is_test_environment', lambda: False)
    db = DatabaseService(tmp_path / 'prefetch.db')
    state = {'uid': 'u', 'request_type': 'USER_COMMAND', 'raw_request': {'text': 'What I did today'}}
    result = LoadContextNode(db)(state)
    assert result['context_history'] is None
    prompt = Tier2AgentNode(db)._build_user_prompt({**state, **result})
    assert 'Prefetched activity history for the explicit requested window' not in prompt
    fs.query_context_memory.assert_not_called()
    fs.query_context_memory.side_effect = RuntimeError('history unavailable')
    result = LoadContextNode(db)(state)
    assert result['context_history'] is None
