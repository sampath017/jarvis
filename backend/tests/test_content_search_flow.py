import json
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from src.models.schemas import CommandRequest
from src.api.routers.file_memories import FileMemory
from src.cloud.file_memory_tools import file_memory_tools
from src.backend.command_execution import CommandExecution, execution
from src.services import drive_index


@pytest.mark.parametrize('url', [
    'https://drive.google.com/file/d/f',
    'https://docs.google.com/document/d/f/edit',
    'https://sites.google.com/view/f',
    'https://aistudio.google.com/app/prompts?state=%7B%22ids%22:%5B%22f%22%5D%7D',
    'https://colab.research.google.com/drive/f',
])
def test_chat_and_indexing_accept_same_google_file_links(url):
    ref = {'id': 'f', 'name': 'Document', 'mimeType': 'application/pdf', 'url': url}
    assert CommandRequest(text='Search the contents too', file_memories=[ref]).file_memories[0].url == url
    assert FileMemory(**ref, size=0, account='a', created_at='').url == url


@pytest.mark.parametrize('url', [
    'https://docs.google.com.evil.invalid/file',
    'https://aistudio.google.com.evil.invalid/file',
    'https://colab.research.google.com.evil.invalid/file',
    'https://aistudio.google.com@evil.invalid/file',
    'http://colab.research.google.com/drive/f',
    'https://evil.invalid/file',
])
def test_lookalike_google_domain_is_rejected(url):
    ref = {'id': 'f', 'name': 'n', 'mimeType': 'text/plain', 'url': url}
    with pytest.raises(ValidationError):
        CommandRequest(text='read', file_memories=[ref])
    with pytest.raises(ValidationError):
        FileMemory(**ref, size=0, account='a', created_at='')


def test_mixed_native_file_references_fit_the_command_context_limit():
    urls = ['https://drive.google.com/file/d/f/view?usp=sharing#page=2',
            'https://aistudio.google.com/app/prompts?state=%7B%7D',
            'https://colab.research.google.com/drive/f?authuser=0']
    refs = [{'id': str(i), 'name': 'ఆధార్.pdf', 'mimeType': 'application/pdf',
             'url': urls[i % len(urls)]} for i in range(12)]
    request = CommandRequest(text='Where was I yesterday at 12:36?', file_memories=refs)
    assert len(request.file_memories) == 12
    with pytest.raises(ValidationError) as error:
        CommandRequest(text='test', file_memories=refs + [refs[0]])
    assert error.value.errors()[0]['loc'] == ('file_memories',)


def test_one_bad_reference_reports_its_exact_location():
    refs = [{'id': str(i), 'name': 'Notebook', 'mimeType': 'text/plain', 'url': url}
            for i, url in enumerate(['https://colab.research.google.com/drive/f',
                                     'https://colab.research.google.com@evil.invalid/f'])]
    with pytest.raises(ValidationError) as error:
        CommandRequest(text='test', file_memories=refs)
    assert [item['loc'] for item in error.value.errors()] == [('file_memories', 1, 'url')]


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
