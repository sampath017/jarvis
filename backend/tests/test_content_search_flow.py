import json
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from src.models.schemas import CommandRequest
from src.api.routers.file_memories import FileMemory
from src.cloud.file_memory_tools import file_memory_tools
from src.backend.command_execution import CommandExecution, execution
from src.services import drive_index


@pytest.mark.parametrize('url', ['https://drive.google.com/file/d/f', 'https://docs.google.com/document/d/f/edit', 'https://sites.google.com/view/f'])
def test_chat_and_indexing_accept_same_google_file_links(url):
    ref = {'id': 'f', 'name': 'Document', 'mimeType': 'application/pdf', 'url': url}
    assert CommandRequest(text='Search the contents too', file_memories=[ref]).file_memories[0].url == url
    assert FileMemory(**ref, size=0, account='a', created_at='').url == url


def test_lookalike_google_domain_is_rejected():
    with pytest.raises(ValidationError):
        CommandRequest(text='read', file_memories=[{'id':'f','name':'n','mimeType':'text/plain','url':'https://docs.google.com.evil.invalid/file'}])


def test_search_tool_defaults_to_reading_contents_and_preserves_full_information_need():
    dispatched = Mock(return_value={'status':'ok'})
    current = CommandExecution(lambda _: None, approval_dispatch=dispatched)
    token = execution.set(current)
    try:
        tool = next(t for t in file_memory_tools() if t.name == 'search_file_memories')
        tool.invoke({'query':'Aadhaar','content_query':'Find my identity document by its contents'})
        assert dispatched.call_args.args[0]['read_contents'] is True
        assert dispatched.call_args.args[0]['content_query'] == 'Find my identity document by its contents'
        tool.invoke({'query':'resume','read_contents':False})
        assert dispatched.call_args.args[0]['read_contents'] is False
    finally:
        execution.reset(token)


def test_batched_passages_are_owner_account_and_live_version_scoped(monkeypatch):
    collection = Mock()
    collection.query.return_value = {'documents': [['Matched body text']], 'metadatas': [[{'file_id':'generic','name':'0042.pdf','locator':'page 1','unit_kind':'text'}]]}
    monkeypatch.setattr(drive_index, 'index', lambda: collection)
    monkeypatch.setattr(drive_index, 'embed', lambda *args: [[0.] * 768])
    result = drive_index.search_contents('owner', 'account', 'identity document', [{'file_id':'generic','source_version':'7'}])
    scope = collection.query.call_args.kwargs['where']['$and']
    assert {'owner':'owner'} in scope and {'account':'account'} in scope
    assert scope[-1] == {'$and':[{'file_id':'generic'},{'source_version':'7'}]}
    assert result['evidence'][0]['text'] == 'Matched body text'
