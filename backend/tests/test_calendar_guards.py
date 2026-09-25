import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from src.backend.command_execution import CommandExecution, execution
from src.cloud.calendar_tools import calendar_tools
from src.services.command_run_store import CommandRunStore
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.services.database import DatabaseService


def test_calendar_tools_require_connected_device_and_report_real_results():
    tools = {t.name: t for t in calendar_tools()}
    assert json.loads(tools['delete_calendar_event'].invoke({'event_id': 'event1'}))['status'] == 'unavailable'
    dispatch = Mock(return_value={'status': 'declined'})
    token = execution.set(CommandExecution(lambda _: None, calendar_dispatch=dispatch))
    try:
        result = tools['delete_calendar_event'].invoke({'event_id': 'event1'})
        assert json.loads(result)['status'] == 'declined'
        assert dispatch.call_args.args[0]['whole_series'] is False
    finally:
        execution.reset(token)


def test_device_capability_required_for_calendar_request():
    data = {'calendar_key_hash': hashlib.sha256(b'private-key').hexdigest()}
    for invalid in (None, '', 'wrong-key'):
        with pytest.raises(HTTPException) as error:
            CommandRunStore.authorize(data, invalid)
        assert error.value.status_code == 403
    CommandRunStore.authorize(data, 'private-key')


def test_public_progress_does_not_expose_calendar_proposals_or_key():
    data = dict(started_at=datetime.now(timezone.utc), request_id='id', message='Working',
        calendar_action={'private': 'event'}, calendar_key_hash='secret')
    public = CommandRunStore.public(data)
    assert 'calendar_action' not in public and 'calendar_key_hash' not in public


@pytest.mark.parametrize('approval', ['declined', 'not_executed', 'approved'])
def test_saved_data_writes_require_device_approval(monkeypatch, tmp_path, approval):
    db = DatabaseService(tmp_path / 'guard.db')
    tool = Mock(); tool.name = 'delete_note'; tool.invoke.return_value = 'Deleted ID: one'
    monkeypatch.setattr('src.graph.nodes.tier2_tools_node.build_tier2_tools', lambda *_: [tool])
    dispatch = Mock(return_value={'status': approval})
    context = CommandExecution(lambda _: None, approval_dispatch=dispatch)
    token = execution.set(context)
    try:
        Tier2ToolsNode(db)({'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[{'name': 'delete_note', 'args': {'id': 'one'}, 'id': 'call'}])]})
        assert tool.invoke.call_count == (1 if approval == 'approved' else 0)
        assert dispatch.call_count == 1
    finally:
        execution.reset(token)
