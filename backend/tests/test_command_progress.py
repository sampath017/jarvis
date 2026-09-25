"""Streaming, reconnect, and cooperative guard regressions without external calls."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import threading
from unittest.mock import Mock
import pytest
from langchain_core.messages import AIMessage
from src.api.routers import commands
from src.backend.command_execution import CommandExecution, CommandStopped, execution, report_progress
from src.models.schemas import APIResponse, CommandRequest
from src.services.command_run_store import CommandRunStore
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.graph.builder import build_workflow
from src.services.database import DatabaseService

class MemoryRuns:
    def __init__(self):
        self.lock = threading.Lock()
        self.runs = {}
    def claim(self, uid, request):
        with self.lock:
            key = (uid, request.request_id)
            if key in self.runs: return False
            self.runs[key] = dict(status='running', message='Request received', sequence=0, steps=[],
                started_at=datetime.now(timezone.utc), request_id=request.request_id, response=None, cancel_requested=False)
            return True
    def get(self, uid, request_id):
        with self.lock: return dict(self.runs[uid, request_id])
    def progress(self, uid, request_id, message):
        with self.lock:
            data = self.runs[uid, request_id]
            data['steps'] = (data['steps'] + [data['message']])[-4:]
            data['message'] = message
            data['sequence'] += 1
    def finish(self, uid, request_id, response):
        with self.lock: self.runs[uid, request_id].update(status='complete', response=response)
    public = staticmethod(CommandRunStore.public)


@pytest.mark.parametrize('status,age', [('queued', 601), ('running', 781)])
def test_delayed_or_uncertain_task_does_not_restart_side_effects(monkeypatch, status, age):
    from src.services import command_run_store as module
    monkeypatch.setattr(module.firestore, 'transactional', lambda f: f)
    store = CommandRunStore.__new__(CommandRunStore)
    store.db = Mock()
    ref, control = Mock(), Mock()
    store.ref = lambda *_: ref
    store.control = lambda *_: control
    ref.get.return_value.to_dict.return_value = {'status': status,
        'started_at': datetime.now(timezone.utc) - timedelta(seconds=age)}
    control.get.return_value.to_dict.return_value = {'request_id': 'newer-request'}
    assert store.start_execution('u', 'old-request') is None
    saved = store.db.transaction.return_value.update.call_args.args[1]
    assert saved['response']['status'] == 'error'
    # An expired worker must not release another request's lock.
    store.db.transaction.return_value.delete.assert_not_called()


def test_reconnect_starts_only_one_worker_and_can_retrieve_saved_result(monkeypatch):
    monkeypatch.setattr(commands, "PushNotifications", Mock())
    store = MemoryRuns()
    monkeypatch.setattr(commands, 'CommandRunStore', lambda: store)
    started, release = threading.Event(), threading.Event()
    calls = []
    def slow(request, uid, workflow):
        calls.append(request.request_id)
        report_progress('Checking your reminders')
        started.set()
        assert release.wait(5)
        return APIResponse(message='Done', run_id='same-answer')
    monkeypatch.setattr(commands, '_execute_user_command', slow)
    async def run():
        request = CommandRequest(request_id='one', thread_id='chat', text='Do it')
        await commands._start_run(request, 'u', None)
        assert await asyncio.to_thread(started.wait, 5)
        events = commands._command_events(store, 'u', 'one')
        first = await anext(events)
        assert 'Checking your reminders' in first
        await events.aclose()  # Mobile lost its stream.
        await commands._start_run(request, 'u', None)
        assert calls == ['one']
        release.set()
        await asyncio.gather(*list(commands._running_tasks))
        reconnected = commands._command_events(store, 'u', 'one')
        result = await anext(reconnected)
        assert 'event: result' in result and 'same-answer' in result
        await reconnected.aclose()
    asyncio.run(run())


def test_deadline_cancel_and_repeated_step_guard():
    context = CommandExecution(lambda _: None, cancelled=lambda: True)
    with pytest.raises(CommandStopped, match='your request'): context.check()
    context = CommandExecution(lambda _: None, started=0)
    with pytest.raises(CommandStopped, match='10 minutes'): context.check()
    context = CommandExecution(lambda _: None)
    for _ in range(3): context.tool_key('list_notes', {})
    with pytest.raises(CommandStopped, match='repeating'): context.tool_key('list_notes', {})


def test_repeated_write_is_not_executed_twice(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'test.db')
    tool = Mock(name='tool')
    tool.name = 'create_note'
    tool.invoke.return_value = 'Saved ID: note-1'
    monkeypatch.setattr('src.graph.nodes.tier2_tools_node.build_tier2_tools', lambda *_: [tool])
    context = CommandExecution(lambda _: None)
    token = execution.set(context)
    try:
        state = {'uid': 'u', 'agent_messages': [AIMessage(content='', tool_calls=[
            {'name': 'create_note', 'args': {'text': 'same'}, 'id': 'a'},
            {'name': 'create_note', 'args': {'text': 'same'}, 'id': 'b'},
        ])]}
        result = Tier2ToolsNode(db)(state)
        assert tool.invoke.call_count == 1
        assert result['agent_messages'][-1].content == 'Saved ID: note-1'
        assert context.changed_records == ['note-1']
    finally: execution.reset(token)


def test_progress_context_reaches_langgraph_worker_threads(tmp_path, monkeypatch):
    class NoCloud:
        is_available = False
    monkeypatch.setattr('src.services.firestore_service.FirestoreService', NoCloud)
    monkeypatch.setattr('src.graph.nodes.persist.FirestoreService', NoCloud)
    messages = []
    token = execution.set(CommandExecution(messages.append))
    try:
        graph = build_workflow(DatabaseService(tmp_path / 'graph.db'))
        result = graph.invoke({'uid': 'u', 'request_type': 'USER_COMMAND',
            'raw_request': {'text': 'hello', 'request_id': 'g', 'thread_id': 'c'}})
        assert result['user_response']
        assert 'Reading your request' in messages
        assert 'Checking your recent context' in messages
        assert 'Saving your response' in messages
    finally: execution.reset(token)


def test_public_status_has_no_prompt_or_model_reasoning():
    data = dict(request_id='a', started_at=datetime.now(timezone.utc), message='Checking your reminders',
        status='running', steps=[], sequence=1, fingerprint='private', prompt='private reasoning', response=None)
    snapshot = CommandRunStore.public(data)
    assert 'fingerprint' not in snapshot and 'prompt' not in snapshot
