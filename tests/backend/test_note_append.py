from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from src.backend.command_execution import CommandExecution, execution
from src.cloud.agent_tools import build_agent_tools
from src.graph.nodes.agent_tools import AgentToolsNode
from src.services.database import DatabaseService


@pytest.fixture
def notes(tmp_path):
    db = DatabaseService(tmp_path / 'notes.db')
    db.create_note('u', {'id': 'habit', 'title': 'Walking log', 'content': 'Earlier entry\nWalked 20 minutes',
                         'place': 'Park', 'tags': ['habit'], 'created_at': '2026-10-01T00:00:00Z'})
    return db, {tool.name: tool for tool in build_agent_tools(db, 'u')}


def test_append_preserves_identity_metadata_and_repeated_habits_on_different_days(notes):
    db, tools = notes
    original = db.get_note('u', 'habit')
    for day in ['2026-10-25', '2026-10-26']:
        result = tools['append_note'].invoke({'note_id': 'habit', 'text': 'Walked 30 minutes', 'entry_date': day})
        assert 'Appended entry' in result
    saved = db.get_note('u', 'habit')
    assert saved['content'] == original['content'] + '\n\n[2026-10-25]\nWalked 30 minutes\n\n[2026-10-26]\nWalked 30 minutes'
    for key in ['id', 'title', 'place', 'tags', 'created_at']:
        assert saved[key] == original[key]
    assert len(db.list_notes('u')) == 1


def test_create_same_subject_appends_instead_of_creating_duplicate(notes):
    db, tools = notes
    result = tools['create_note'].invoke({'title': ' walking LOG ', 'text': 'Walked 40 minutes'})
    assert 'Appended entry' in result
    assert len(db.list_notes('u')) == 1
    assert db.get_note('u', 'habit')['content'].endswith('Walked 40 minutes')


def test_ambiguous_subject_asks_without_writing(notes):
    db, tools = notes
    db.create_note('u', {'id': 'other', 'title': 'Walking log', 'content': 'Other log'})
    before = db.list_notes('u')
    result = tools['create_note'].invoke({'title': 'Walking log', 'text': 'Walked today'})
    assert 'Ask the user which note' in result
    assert all(note_id in result for note_id in ['habit', 'other'])
    assert db.list_notes('u') == before


def test_explicit_separate_note_is_allowed(notes):
    db, tools = notes
    result = tools['create_note'].invoke({'title': 'Walking log', 'text': 'Separate trip', 'new_note': True})
    assert 'Successfully created' in result
    assert len(db.list_notes('u')) == 2


@pytest.mark.parametrize('arguments', [
    {'note_id': 'foreign', 'text': 'private'},
    {'note_id': 'trashed', 'text': 'deleted'},
    {'note_id': 'missing', 'text': 'missing'},
    {'note_id': 'habit', 'text': ''},
    {'note_id': 'habit', 'text': 'entry', 'entry_date': 'yesterday'},
])
def test_invalid_destination_or_entry_does_not_write(notes, arguments):
    db, tools = notes
    db.create_note('other-user', {'id': 'foreign', 'content': 'Private'})
    db.create_note('u', {'id': 'trashed', 'content': 'Deleted', 'deleted_at': '2026-10-01'})
    before = db.list_notes('u', include_deleted=True)
    assert tools['append_note'].invoke(arguments).startswith('Not saved:')
    assert db.list_notes('u', include_deleted=True) == before


def test_search_finds_old_subject_and_excludes_trash_and_other_users(notes):
    db, tools = notes
    for index in range(60):
        db.create_note('u', {'title': 'Unrelated', 'content': str(index)})
    db.create_note('u', {'id': 'trash', 'title': 'Walking log', 'deleted_at': '2026-10-20'})
    db.create_note('someone-else', {'id': 'foreign', 'title': 'Walking log', 'content': 'Private'})
    result = tools['search_notes'].invoke({'query': 'Walking'})
    assert 'Walking log' in result and 'habit' in result and 'Park' in result
    assert 'foreign' not in result and 'trash' not in result


def test_append_is_a_routine_write_deduplicated_within_one_command(notes):
    db, _ = notes
    dispatch = Mock(side_effect=AssertionError('Appending an authorized entry needs no approval'))
    context = CommandExecution(lambda _: None, approval_dispatch=dispatch)
    token = execution.set(context)
    try:
        args = {'note_id': 'habit', 'text': 'New daily entry', 'entry_date': '2026-10-26'}
        result = AgentToolsNode(db)({'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[
            {'name': 'append_note', 'args': args, 'id': 'one'},
            {'name': 'append_note', 'args': args, 'id': 'two'},
        ])]})
    finally:
        execution.reset(token)
    assert db.get_note('u', 'habit')['content'].count('New daily entry') == 1
    assert result['changed_records'] == ['habit', 'habit']
    assert context.changed_records == ['habit']
    dispatch.assert_not_called()


@pytest.mark.parametrize('user_text', ["No need new note", "Don't create a new note", "Do not make a separate note", "No need new note, don't delete anything"])
@pytest.mark.parametrize('name,args', [('delete_note', {'note_id': 'habit'}), ('delete_all_notes', {})])
def test_declining_new_note_does_not_authorize_deletion(notes, user_text, name, args):
    db, _ = notes
    original = db.get_note('u', 'habit')
    result = AgentToolsNode(db)({'uid': 'u', 'raw_request': {'text': user_text}, 'agent_messages': [
        AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': 'bad-interpretation'}]),
    ]})
    assert result['agent_messages'][-1].content.startswith('Not executed:')
    assert db.get_note('u', 'habit') == original
    assert not result['changed_records']


def test_explicit_deletion_after_declining_new_note_still_works(notes):
    db, _ = notes
    result = AgentToolsNode(db)({'uid': 'u', 'raw_request': {'text': 'No need new note, delete that one'}, 'agent_messages': [
        AIMessage(content='', tool_calls=[{'name': 'delete_note', 'args': {'note_id': 'habit'}, 'id': 'delete'}]),
    ]})
    assert 'Moved note' in result['agent_messages'][-1].content
    assert db.get_note('u', 'habit')['deleted_at']
