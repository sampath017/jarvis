"""Regression coverage for the unnecessary call-reminder confirmation loop."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.backend.command_execution import CommandExecution, execution
from src.backend.reminder_tool_contract import ground_relative_call, reminder_input_error
from src.cloud.agent_tools import build_agent_tools
from src.graph.builder import build_workflow
from src.services.database import DatabaseService


@pytest.mark.parametrize('text,seconds', [
    ('Call me in next 10 sec', 10), ('please call me in 10sec.', 10),
    ('Ring me after 2 minutes', 120), ('give me a call in the next 1 hour', 3600),
])
def test_explicit_relative_call_is_grounded_in_user_request(text, seconds):
    assert ground_relative_call(text, {'due_at': 'bad', 'activity': 'WALKING'}) == {
        'title': 'Call reminder', 'due_at': f'in {seconds} seconds', 'delivery_mode': 'in_app_call',
    }


@pytest.mark.parametrize('text', [
    'Call my mother in 10 seconds', 'Do not call me in 10 seconds',
    'Call me in 10 seconds and save a note', 'Call me in 10 seconds when I get home',
    'Call me in 0 sec', 'Call me in -10 sec', 'Call me in 10 months',
    'Do you support call me in 10 seconds?',
])
def test_grounding_never_reinterprets_negation_other_people_or_mixed_requests(text):
    arguments = {'title': 'Original', 'due_at': 'original'}
    assert ground_relative_call(text, arguments) == arguments


def graph_with_script(monkeypatch, tmp_path, invoke):
    db = DatabaseService(tmp_path / 'reminder-recovery.db')
    model = Mock()
    model.bind_tools.return_value.invoke.side_effect = invoke
    monkeypatch.setattr('src.graph.nodes.agent.ChatOpenAI', lambda **_: model)
    return db, model, build_workflow(db=db)


def tool_call(arguments, id='reminder'):
    return AIMessage(content='', tool_calls=[{'name': 'create_reminder', 'args': arguments, 'id': id}])


def test_policy_edit_recovers_from_model_delete_without_permission_or_losing_original(monkeypatch, tmp_path):
    turns=[]
    def invoke(messages):
        turns.append(messages)
        if len(turns)==1:
            return AIMessage(content='',tool_calls=[{'name':'delete_reminder','args':{'reminder_id':'milk'},'id':'wrong-delete'}])
        if len(turns)==2:
            assert any(isinstance(m,ToolMessage) and 'edit_in_place' in m.content for m in messages)
            return AIMessage(content='',tool_calls=[{'name':'update_reminder','args':{'reminder_id':'milk','journey_origin':'Gym','delivery_mode':'in_app_call'},'id':'edit'}])
        return AIMessage(content='Updated your existing milk policy to call after leaving Gym. No shop condition.')
    db,model,graph=graph_with_script(monkeypatch,tmp_path,invoke)
    db.create_place('regression',{'name':'Gym','latitude':12.,'longitude':80.})
    db.create_reminder('regression',{'id':'milk','title':'Buy milk','dynamic_policy':{'version':1,'category':'supermarket'},'activity':'WALKING'})
    result,context=execute(graph,'Update my milk policy: after I leave Gym, no shop condition, make it a call')
    record,=db.list_reminders('regression')
    assert record['id']=='milk' and record['status']=='ACTIVE' and record['activity'] is None
    assert record['delivery_mode']=='in_app_call' and 'category' not in json.loads(record['dynamic_policy'])
    assert context.changed_records==['milk']
    assert len(turns)==3


def test_actual_deletion_keeps_the_existing_approval_path():
    from src.backend.reminder_tool_contract import reminder_edit_requested
    history=[{'role':'user','content':'Update the milk reminder'}]
    assert not reminder_edit_requested({'text':'Delete the milk reminder','history':history})
    assert reminder_edit_requested({'text':'Remove the shop condition from the reminder','history':history})


def execute(graph, text, history=()):
    approvals = Mock(side_effect=AssertionError('Routine reminders must not ask for approval'))
    context = CommandExecution(lambda _: None, approval_dispatch=approvals)
    token = execution.set(context)
    try:
        result = graph.invoke({'uid': 'regression', 'request_type': 'USER_COMMAND',
            'raw_request': {'request_id': 'call-regression', 'thread_id': 'test-chat',
                            'text': text, 'history': list(history)}})
    finally:
        execution.reset(token)
    approvals.assert_not_called()
    return result, context


def test_call_in_ten_seconds_saves_once_without_confirmation_and_keeps_24_messages(monkeypatch, tmp_path):
    turns = []
    def invoke(messages):
        turns.append(messages)
        if len(turns) == 1:
            # Reproduce a model omitting the explicit delay and adding unrelated
            # conditions. Execution must use the user's unambiguous request.
            return tool_call({'title': 'Call me', 'activity': 'WALKING', 'confirmed': False})
        assert any(isinstance(m, ToolMessage) and 'Successfully created reminder' in m.content for m in messages)
        return AIMessage(content='Your Jarvis call reminder is set for 10 seconds from now.')
    db, model, graph = graph_with_script(monkeypatch, tmp_path, invoke)
    history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': f'Prior message {i}'} for i in range(24)]
    before = datetime.now(timezone.utc)
    # Verify the scheduling contract independently of a busy machine's graph latency.
    class ReminderClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return before.astimezone(tz) if tz else before.replace(tzinfo=None)
    monkeypatch.setattr('src.cloud.agent_tools.datetime', ReminderClock)
    result, context = execute(graph, 'Call me in next 10 sec', history)
    reminders = db.list_reminders('regression')
    assert len(reminders) == 1
    saved = reminders[0]
    assert saved['delivery_mode'] == 'in_app_call'
    assert saved['activity'] is None and saved['latitude'] is None
    assert 9 <= (datetime.fromisoformat(saved['due_at']) - before).total_seconds() <= 15
    assert result['changed_records'] == [saved['id']]
    assert sum('\nPrior message ' in m.content for m in turns[0]) == 24
    assert not result.get('needs_user_input') and not result.get('error')
    assert model.bind_tools.return_value.invoke.call_count == 2
    assert len(context.writes) == 1


def test_agent_can_correct_failed_time_arguments_before_retry(monkeypatch, tmp_path):
    count = 0
    def invoke(messages):
        nonlocal count
        count += 1
        if count == 1:
            return tool_call({'title': 'Drink water', 'due_at': 'invalid'})
        if count == 2:
            failure = json.loads(messages[-1].content)
            assert failure['code'] == 'invalid_time'
            assert failure['requires_approval'] is False
            return tool_call({'title': 'Drink water', 'due_at': 'in 10 seconds'}, id='fixed')
        assert 'Successfully created reminder' in messages[-1].content
        return AIMessage(content='Water reminder saved for 10 seconds from now.')
    db, _, graph = graph_with_script(monkeypatch, tmp_path, invoke)
    result, _ = execute(graph, 'Remind me to drink water in 10 seconds')
    assert len(db.list_reminders('regression')) == 1
    assert count == 3 and not result.get('error')


def test_unchanged_failed_retry_and_confirmed_flag_do_not_loop_or_claim_success(monkeypatch, tmp_path, caplog):
    count = 0
    def invoke(_):
        nonlocal count
        count += 1
        return tool_call({'title': 'Private title must not enter outcome logs', 'confirmed': count > 1})
    db, _, graph = graph_with_script(monkeypatch, tmp_path, invoke)
    with caplog.at_level('INFO'):
        result, context = execute(graph, 'Remind me')
    assert count == 2  # The next graph turn terminates without another model call.
    assert db.list_reminders('regression') == []
    assert result['changed_records'] == [] and not result.get('error')
    assert 'Supply a reminder time' in result['user_response']
    assert 'confirm' not in result['user_response'].lower()
    outcomes = [r.message for r in caplog.records if 'Tool outcome' in r.message]
    assert len(outcomes) == 2
    assert all('status=invalid_arguments code=missing_trigger' in m for m in outcomes)
    assert all('Private title' not in m for m in outcomes)
    assert len(context.writes) == 1


def test_invalid_reminder_arguments_never_request_approval_or_create_a_record(tmp_path):
    db = DatabaseService(tmp_path / 'invalid.db')
    tools = {t.name: t for t in build_agent_tools(db, 'regression')}
    error = json.loads(tools['create_reminder'].invoke({'title': 'Call', 'due_at': '10'}))
    assert error['status'] == 'invalid_arguments' and error['code'] == 'invalid_time'
    assert error['saved'] is False and error['requires_approval'] is False
    assert db.list_reminders('regression') == []
    assert json.loads(reminder_input_error('missing_trigger', 'due_at', 'Missing time'))['field'] == 'due_at'


def test_legacy_confirmed_argument_is_hidden_from_model_but_remains_compatible(tmp_path):
    db = DatabaseService(tmp_path / 'compatibility.db')
    tools = {t.name: t for t in build_agent_tools(db, 'regression')}
    for name in ('create_reminder', 'update_reminder'):
        assert 'confirmed' not in tools[name].tool_call_schema.model_json_schema()['properties']
    saved = tools['create_reminder'].invoke({'title': 'Compatibility', 'due_at': 'in 10 seconds', 'confirmed': True})
    assert 'Successfully created reminder' in saved
    reminder = db.list_reminders('regression')[0]
    updated = tools['update_reminder'].invoke({'reminder_id': reminder['id'], 'title': 'Updated', 'confirmed': True})
    assert 'Successfully updated reminder' in updated
