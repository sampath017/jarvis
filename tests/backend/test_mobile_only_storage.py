"""Production mobile mode: real RAM SQL, scoped reads, and change delivery."""
import json
import uuid
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from src.services.mobile_scope import MobileScope, current
from src.services.record_store import RecordStore
from src.services import sqlite_documents
from src.services.database import DatabaseService

@pytest.fixture(autouse=True)
def mobile(monkeypatch):
    monkeypatch.setenv('JARVIS_STORAGE_MODE', 'mobile')
    monkeypatch.setattr(RecordStore, '_init_db', lambda self: setattr(self, '_db', sqlite_documents.Client()))

@contextmanager
def scope(seed=None):
    state=MobileScope(); token=current.set(state)
    try:
        state.seed(seed or {})
        yield state
    finally:
        current.reset(token);state.release()

def test_no_scope_cannot_open_persistent_store():
    with pytest.raises(RuntimeError): RecordStore()
    with pytest.raises(RuntimeError): DatabaseService().list_notes('jarvis_local_user')

def test_requested_read_does_not_hide_prior_writes_and_scopes_are_isolated():
    uid='jarvis_local_user'
    with scope() as state:
        db=DatabaseService();fs=RecordStore()
        db.create_note(uid, {'id':'created','content':'new local note'})
        fs.save_note('created', {'id':'created','uid':uid,'content':'new local note'})
        state.import_read({'records':{'notes':[{'id':'existing','content':'phone content','updated_at':'v1'}]}})
        delta=state.changes()
        assert [r['id'] for r in delta['records']['notes']]==['created']
        fs.save_note('existing',{'content':'edited','updated_at':'v2'})
        assert {r['id'] for r in state.changes()['records']['notes']}=={'created','existing'}
        assert state.base_versions['notes']['existing']=='v1'
        with scope() as other:
            assert DatabaseService().list_notes(uid)==[]
            assert RecordStore().get_notes(uid)==[]
        assert len(db.list_notes(uid))==2
    assert state.closed and other.closed

def test_composite_domain_keys_and_deletion_roundtrip():
    with scope({'agent':{'domain':{'context_trigger_state':[{'uid':'old','source_type':'reminder','source_id':'r','is_inside':1}]}}}) as state:
        row=state.snapshot()['context_trigger_state'][0]
        assert json.loads(row['__key'])==['jarvis_local_user','reminder','r']
        state.db.execute('DELETE FROM context_trigger_state')
        assert state.changes()['agent']['domain_deleted']['context_trigger_state']==[row['__key']]

def test_task_read_is_baseline_then_updates_return():
    with scope() as state:
        state.import_read({'agent':{'domain':{'tasks':[{'id':'t','title':'phone task','uid':'ignored','created_at':'now','updated_at':'now'}]}}})
        assert state.changes()['agent']['domain']['tasks']==[]
        state.db.execute("UPDATE tasks SET title='changed'")
        assert state.changes()['agent']['domain']['tasks'][0]['title']=='changed'

def test_http_mobile_routes_parse_and_greeting_are_stateless(tmp_path,monkeypatch):
    monkeypatch.setenv('JARVIS_LOCAL_DB_PATH',str(tmp_path/'must-not-exist.db'))
    from src.api.main import create_app
    from src.api.dependencies import get_workflow
    get_workflow.cache_clear()
    with TestClient(create_app()) as client:
        assert client.get('/health').json()['storage']['server_storage']=='request-memory'
        paths=client.get('/openapi.json').json()['paths']
        assert '/sync/push' not in paths and '/internal/background/command' not in paths
        assert '/chat-archives/policy' not in paths and '/file-memories' not in paths
        parsed=client.post('/mobile/parse-file',content=b'Invoice reference ABC123',headers={'content-type':'text/plain','x-file-mime':'text/plain','x-file-name':'example.txt'})
        assert parsed.status_code==200,parsed.text
        assert 'ABC123' in parsed.json()['chunks'][0]['text']
        response=client.post('/commands/stream',json={'request_id':uuid.uuid4().hex,'thread_id':'smoke','text':'hello'})
        assert response.status_code==200,response.text
        result=json.loads(response.text.split('event: result\ndata: ')[1].split('\n\n')[0])
        assert result['status']=='ok',result
        assert result['_mobile_changes']['operation_id']
        event_id=uuid.uuid4().hex
        event=client.post('/context-events',json={'event_id':event_id,'event_type':'ACTIVITY_ENTER','activity':'WALKING','transition':'ENTER'})
        assert event.status_code==202,event.text
        assert event.json()['status']=='ok',event.text
        changes=event.json()['_mobile_changes']
        assert changes['operation_id']=='event:'+event_id
        observations=[r for r in changes['agent']['documents'] if r['collection'].endswith('/context_memory')]
        assert observations and observations[0]['data']['activity']=='WALKING'
    assert not (tmp_path/'must-not-exist.db').exists()
    get_workflow.cache_clear()

def test_budget_old_day_resets_delta():
    from src.api.rate_limiter import TokenBudgetGuard
    from datetime import date
    with scope({'budget':{'day':'2000-01-01','cost_nanos':1000}}) as state:
        TokenBudgetGuard()._mutate_usage_impl('u',date(2026,10,24),lambda r:setattr(r,'cost_nanos',50))
        assert state.changes()['budget']['cost_nanos']==50

def test_agent_tool_reads_phone_record_before_editing():
    from src.backend.command_execution import CommandExecution, execution
    from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
    from langchain_core.messages import AIMessage
    calls=[]
    with scope() as state:
        context=CommandExecution(publish=lambda _:None)
        def read(action):
            calls.append(action)
            return {'status':'ok','state':{'records':{'notes':[{'id':'n','content':'phone original','updated_at':'v1'}]}}}
        context.approval_dispatch=read
        token=execution.set(context)
        try:
            Tier2ToolsNode()({'uid':'jarvis_local_user','agent_messages':[AIMessage(content='',tool_calls=[{'name':'update_note','args':{'note_id':'n','text':'requested edit'},'id':'call'}])]})
        finally: execution.reset(token)
        assert calls[0]['operation']=='local_read'
        assert calls[0]['arguments']=={'note_id':'n','text':'requested edit'}
        assert state.changes()['records']['notes'][0]['content']=='requested edit'
