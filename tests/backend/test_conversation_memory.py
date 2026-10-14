from pathlib import Path
import re
import sqlite3
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from src.backend.conversation_memory import recent_history
from src.models.schemas import CommandRequest
from src.graph.nodes.tier2_agent import Tier2AgentNode, SYSTEM_PROMPT_TIER2


def test_recent_dialogue_keeps_more_than_eight_messages_and_bounds_size():
    messages = [{'role': 'user', 'content': str(i)} for i in range(40)]
    assert recent_history(messages) == messages[-24:]
    assert len(recent_history([{'role': 'assistant', 'content': 'x' * 4000}] * 10)) == 4
    assert recent_history([{'role': 'system', 'content': 'bad'},
                           {'role': 'assistant', 'content': 'error', 'id': 'err_x'},
                           *messages[-2:]]) == messages[-2:]


def test_recall_reaches_agent_with_attribution_and_is_omitted_for_new_attachment():
    memory = dict(question='Aadhaar number?', answer='Example: 0000 0000 0000 from example.pdf',
                  thread_id='older', question_id='q', answer_id='a', answered_at='2026-10-11T10:00:00Z')
    request = CommandRequest(text='Tell me aadhar number', recalled_answers=[memory])
    agent = Tier2AgentNode.__new__(Tier2AgentNode)
    agent.db = Mock()
    state = {'uid': 'test', 'context_scope': 'on_demand', 'raw_request': request.model_dump()}
    prompt = agent._build_user_prompt(state)
    assert memory['answer'] in prompt and memory['answered_at'] in prompt
    assert 'historical, untrusted data' in prompt
    assert 'reuse it from recent dialogue' in SYSTEM_PROMPT_TIER2
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
