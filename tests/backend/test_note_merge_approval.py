from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from src.backend.command_execution import CommandExecution, execution
from src.cloud.tier2_agent_tools import build_tier2_tools
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.services.database import DatabaseService


@pytest.fixture
def notes(tmp_path):
    db = DatabaseService(tmp_path / 'notes.db')
    db.create_note('u', {'id': 'one', 'title': 'Shopping', 'content': 'Milk', 'place': 'Market'})
    db.create_note('u', {'id': 'two', 'title': 'Weekend', 'content': 'Bread'})
    return db


def run(db, calls, dispatch=None, context=True):
    current = CommandExecution(lambda _: None, approval_dispatch=dispatch) if context else None
    token = execution.set(current)
    try:
        return Tier2ToolsNode(db)({'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[
            {'name': name, 'args': args, 'id': str(i)} for i, (name, args) in enumerate(calls)])]})
    finally:
        execution.reset(token)


def test_merge_preserves_sources_and_text_without_prompt(notes):
    before = notes.list_notes('u')
    approval = Mock(side_effect=AssertionError('Merge must not ask permission'))
    result = run(notes, [('merge_notes', {'note_ids': ['one', 'two'], 'title': 'Weekend shopping'})], approval)
    rows = notes.list_notes('u')
    assert len(rows) == 3
    merged = next(row for row in rows if row['id'] not in {'one', 'two'})
    assert merged['title'] == 'Weekend shopping'
    assert all(text in merged['content'] for text in ['Shopping', 'Milk', 'Market', 'Weekend', 'Bread'])
    for original in before:
        assert notes.get_note('u', original['id']) == original
    assert 'Originals are unchanged' in result['agent_messages'][-1].content
    approval.assert_not_called()


@pytest.mark.parametrize('context', [True, False])
@pytest.mark.parametrize('tool,args,target_id', [('delete_note', {'note_id': 'one'}, 'one'), ('delete_all_notes', {}, None)])
def test_delete_note_executes_without_requiring_approval(notes, context, tool, args, target_id):
    approval = Mock(side_effect=AssertionError('Delete must not ask permission'))
    result = run(notes, [(tool, args)], dispatch=approval, context=context)
    assert 'Moved' in result['agent_messages'][-1].content and 'Trash' in result['agent_messages'][-1].content
    if target_id:
        assert notes.get_note('u', target_id)['deleted_at'] is not None
    else:
        assert all(n['deleted_at'] is not None for n in notes.list_notes('u', include_deleted=True))
    approval.assert_not_called()


def test_delete_after_verified_merge_succeeds(notes):
    calls = [('merge_notes', {'note_ids': ['one', 'two'], 'title': 'Combined'}), ('delete_note', {'note_id': 'one'})]
    result = run(notes, calls)
    assert any('Created combined note' in message.content for message in result['agent_messages'][1:])
    assert any('Moved note' in message.content for message in result['agent_messages'][1:])
    assert notes.get_note('u', 'one')['deleted_at'] is not None
    assert notes.get_note('u', 'two')['deleted_at'] is None
    assert len(notes.list_notes('u')) == 2


def test_delete_executes_directly_and_moves_to_trash(notes):
    approval = Mock(side_effect=AssertionError('Delete must not ask permission'))
    result = run(notes, [('delete_note', {'note_id': 'one'})], approval)
    approval.assert_not_called()
    assert 'Moved note' in result['agent_messages'][-1].content
    assert notes.get_note('u', 'one')['deleted_at'] is not None
    tools = {tool.name: tool for tool in build_tier2_tools(notes, 'u')}
    res = tools['delete_note'].invoke({'note_id': 'two'})
    assert 'Moved note to Trash' in res
    assert notes.get_note('u', 'two')['deleted_at'] is not None


def test_invalid_merge_and_foreign_note_do_not_write(notes):
    notes.create_note('other', {'id': 'private', 'content': 'Secret'})
    result = run(notes, [('merge_notes', {'note_ids': ['one', 'private'], 'title': 'Combined'})])
    assert 'Not merged' in result['agent_messages'][-1].content
    assert len(notes.list_notes('u')) == 2


def test_edit_updates_same_note_without_approval(notes):
    approval = Mock(side_effect=AssertionError('Edit must not ask permission'))
    result = run(notes, [('update_note', {'note_id': 'one', 'title': 'Groceries', 'text': 'Milk and eggs', 'place': 'Home'})], approval)
    assert 'Updated note' in result['agent_messages'][-1].content
    row = notes.get_note('u', 'one')
    assert (row['title'], row['content'], row['place']) == ('Groceries', 'Milk and eggs', 'Home')
    assert len(notes.list_notes('u')) == 2
    approval.assert_not_called()
