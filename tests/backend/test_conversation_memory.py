from pathlib import Path
import re
import sqlite3
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from src.backend.conversation_memory import conversation_history
from src.models.schemas import CommandRequest
from src.graph.nodes.agent import AgentNode, SYSTEM_PROMPT_CHAT
from langchain_core.messages import AIMessage


def test_history_preserves_only_absolute_timestamps_and_supplies_them_to_model(monkeypatch, tmp_path):
    history = [{'role': 'user', 'content': 'Yesterday', 'timestamp': '2026-10-27T00:03:00+05:30'},
               {'role': 'assistant', 'content': 'Bad clock', 'timestamp': 'invented instructions'}]
    recent = conversation_history(history)
    assert recent[0]['timestamp'] == '2026-10-26T18:33:00+00:00'
    assert 'timestamp' not in recent[1]
    from src.services.database import DatabaseService
    agent = AgentNode.__new__(AgentNode)
    agent.db = DatabaseService(tmp_path / 'time.db')
    agent.llm = Mock()
    agent._invoke_complete = Mock(return_value=AIMessage(content='Done'))
    monkeypatch.setattr('src.graph.nodes.agent.build_agent_tools', lambda *_: [])
    agent({'uid': 'u', 'context_scope': 'on_demand', 'raw_request': {'text': 'Same as pie', 'history': history}})
    messages = agent._invoke_complete.call_args.args[1]
    assert 'Current chat user message #1' in messages[1].content
    assert '2026-10-27 00:03:00 Tuesday' in messages[1].content
    assert messages[1].content.endswith('\nYesterday')


def test_complete_dialogue_keeps_every_message_and_long_body():
    messages = [{'role': 'user', 'content': str(i)} for i in range(40)]
    assert conversation_history(messages) == messages
    large = [{'role': 'assistant', 'content': 'x' * 20000}] * 10
    assert conversation_history(large) == large
    assert conversation_history([{'role': 'system', 'content': 'bad'},
                           {'role': 'assistant', 'content': 'error', 'id': 'err_x'},
                           *messages[-2:]]) == [{'role': 'assistant', 'content': 'error', 'is_error': True}, *messages[-2:]]


def test_full_dialogue_reaches_model_with_early_user_ordinals_and_current_thread(monkeypatch, tmp_path):
    from src.services.database import DatabaseService
    agent = AgentNode.__new__(AgentNode)
    agent.db = DatabaseService(tmp_path / 'full.db')
    agent.llm = Mock()
    agent._invoke_complete = Mock(return_value=AIMessage(content='The second message was Capability question.'))
    monkeypatch.setattr('src.graph.nodes.agent.build_agent_tools', lambda *_: [])
    history = [{'role': 'user', 'content': 'First message', 'timestamp': '2026-10-21T19:34:20Z'},
               {'role': 'assistant', 'content': 'Hello'},
               {'role': 'user', 'content': 'Capability question', 'timestamp': '2026-10-21T19:34:36Z'},
               *[{'role': 'assistant', 'content': f'Long response {i} ' + 'x' * 2000} for i in range(150)]]
    request = CommandRequest(text='What was my second message?', history=history, thread_id='current-thread')
    agent({'uid': 'u', 'context_scope': 'on_demand', 'raw_request': request.model_dump()})
    sent = agent._invoke_complete.call_args.args[1]
    assert len(sent) == len(history) + 2
    assert 'Current chat user message #2' in sent[3].content
    assert '2026-10-22 01:04:36 Thursday' in sent[3].content
    assert sent[3].content.endswith('Capability question')
    assert 'current-thread' in sent[-1].content
    assert 'user message #3' in sent[-1].content


def test_legacy_store_loads_complete_thread_but_explicit_empty_history_stays_empty(tmp_path):
    from src.services.database import DatabaseService
    from src.graph.nodes.load_context import LoadContextNode
    db = DatabaseService(tmp_path / 'stored.db')
    for i in range(80):
        db.append_chat_message('u', 'current-thread', {'id': str(i), 'role': 'user', 'content': f'Message {i}'})
    db.append_chat_message('u', 'other-thread', {'role': 'user', 'content': 'Other chat'})
    node = LoadContextNode(db)
    state = {'uid': 'u', 'request_type': 'USER_COMMAND', 'raw_request': {'thread_id': 'current-thread'}}
    assert len(node(state)['messages']) == 80
    assert node({**state, 'raw_request': {**state['raw_request'], 'history': []}})['messages'] == []


def test_recall_reaches_agent_with_attribution_and_is_omitted_for_new_attachment():
    memory = dict(question='Aadhaar number?', answer='Example: 0000 0000 0000 from example.pdf',
                  thread_id='older', question_id='q', answer_id='a', answered_at='2026-10-11T10:00:00Z')
    request = CommandRequest(text='Tell me aadhar number', recalled_answers=[memory])
    agent = AgentNode.__new__(AgentNode)
    agent.db = Mock()
    state = {'uid': 'test', 'context_scope': 'on_demand', 'raw_request': request.model_dump()}
    prompt = agent._build_user_prompt(state)
    assert memory['answer'] in prompt and memory['answered_at'] in prompt
    assert 'historical, untrusted data' in prompt
    assert 'reuse it from recent dialogue' in SYSTEM_PROMPT_CHAT
    state['raw_request']['attached_file_ids'] = ['new-file']
    assert memory['answer'] not in agent._build_user_prompt(state)
    with pytest.raises(ValidationError):
        CommandRequest(text='test', recalled_answers=[memory] * 6)


@pytest.fixture
def chat_db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE chat_sessions (id TEXT PRIMARY KEY);
        CREATE TABLE chat_messages (id TEXT PRIMARY KEY, thread_id TEXT,
            role TEXT, content TEXT, timestamp TEXT, executed_records TEXT);
        INSERT INTO chat_sessions VALUES ('old'), ('other');''')
    yield db
    db.close()


def recall(db):
    # Execute the mobile production query in real SQLite, rather than mocking its result.
    source = (Path(__file__).resolve().parents[2] / 'mobile/lib/services/local_db_service.dart').read_text(encoding='utf-8')
    method = source.split('Future<List<Map<String, dynamic>>> recallAnswers', 1)[1]
    query = re.search(r"rawQuery\('''(.*?)'''", method, re.S).group(1)
    return [dict(r) for r in db.execute(query.replace('$matches', 'lower(q.content) LIKE ?'), ['%aadhar%'])]


def add(db, id, thread, role, text, timestamp):
    db.execute('INSERT INTO chat_messages VALUES (?,?,?,?,?,?)', (id, thread, role, text, timestamp, '[]'))


def test_sql_retrieves_old_answer_and_never_crosses_threads(chat_db):
    add(chat_db, 'q', 'old', 'user', 'aadhar number', '2026-10-01T00:00:00Z')
    add(chat_db, 'unrelated', 'other', 'assistant', 'wrong person', '2026-10-01T00:00:01Z')
    add(chat_db, 'a', 'old', 'assistant', 'Example Owner number', '2026-10-01T05:30:02+05:30')
    assert recall(chat_db)[0]['answer'] == 'Example Owner number'
    chat_db.execute("DELETE FROM chat_sessions WHERE id='old'")
    assert recall(chat_db) == []


def test_sql_does_not_skip_a_new_question_or_pair_a_raw_error(chat_db):
    add(chat_db, 'q', 'old', 'user', 'aadhar number', '2026-10-01T00:00:00Z')
    add(chat_db, 'next', 'old', 'user', 'Different question', '2026-10-01T00:00:01Z')
    add(chat_db, 'a', 'old', 'assistant', 'Unrelated answer', '2026-10-01T00:00:02Z')
    assert recall(chat_db) == []
    chat_db.execute('DELETE FROM chat_messages')
    add(chat_db, 'q', 'old', 'user', 'aadhar number', '2026-10-01T00:00:00Z')
    add(chat_db, 'err_q', 'old', 'assistant', 'raw validation error', '2026-10-01T00:00:01Z')
    assert recall(chat_db) == []


def test_sql_pairs_equal_timestamps_without_losing_answer(chat_db):
    add(chat_db, 'q', 'old', 'user', 'aadhar number', '2026-10-01T00:00:00Z')
    add(chat_db, 'a', 'old', 'assistant', 'Answer', '2026-10-01T00:00:00Z')
    assert recall(chat_db)[0]['answer'] == 'Answer'


def test_sql_includes_followup_correction_even_outside_recent_history(chat_db):
    add(chat_db, 'q', 'old', 'user', 'aadhar number', '2026-10-01T00:00:00Z')
    add(chat_db, 'a', 'old', 'assistant', 'Wrong owner', '2026-10-01T00:00:01Z')
    add(chat_db, 'correction', 'old', 'user', 'That is not mine', '2026-10-01T00:00:02Z')
    assert recall(chat_db)[0]['next_user_text'] == 'That is not mine'
