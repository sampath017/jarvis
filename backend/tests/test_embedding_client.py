from unittest.mock import Mock
import httpx
import pytest
from src.services import drive_index


def test_private_embedding_call_uses_iam_audience_and_explicit_vector_output(monkeypatch):
    monkeypatch.setenv('EMBEDDING_URL', 'https://private.run.app')
    drive_index._token_cache.clear()
    token = Mock(return_value='iam-test-token')
    monkeypatch.setattr('google.oauth2.id_token.fetch_id_token', token)
    post = Mock(return_value=httpx.Response(200, request=httpx.Request('POST', 'https://private.run.app/embed'),
        json={'revision': drive_index.MODEL_REVISION, 'dimensions': 768, 'embeddings': [[0.] * 768]}))
    monkeypatch.setattr(drive_index.httpx, 'post', post)
    assert len(drive_index.embed([{'kind': 'text', 'text': 'receipt'}], 'query')[0]) == 768
    assert token.call_args.args[1] == 'https://private.run.app'
    assert post.call_args.kwargs['headers'] == {'Authorization': 'Bearer iam-test-token'}
    assert post.call_args.kwargs['json']['task'] == 'query'
    assert post.call_args.kwargs['timeout'] == 25
    drive_index.embed([{'kind': 'text', 'text': 'second'}])
    assert token.call_count == 1


def test_embedding_rejects_wrong_model_revision(monkeypatch):
    monkeypatch.setenv('EMBEDDING_URL', 'http://127.0.0.1:8080')
    monkeypatch.setattr(drive_index.httpx, 'post', Mock(return_value=httpx.Response(200,
        request=httpx.Request('POST', 'http://127.0.0.1:8080/embed'),
        json={'revision': 'wrong', 'dimensions': 768, 'embeddings': [[0.] * 768]})))
    with pytest.raises(ValueError, match='version mismatch'):
        drive_index.embed([{'kind': 'text', 'text': 'test'}])


def test_background_embedding_retries_transient_disconnect_without_shortening_query_deadline(monkeypatch):
    monkeypatch.setenv('EMBEDDING_URL', 'http://127.0.0.1:8080')
    monkeypatch.setattr(drive_index.time, 'sleep', lambda _: None)
    post = Mock(side_effect=[httpx.RemoteProtocolError('connection closed'), httpx.Response(200,
        request=httpx.Request('POST', 'http://127.0.0.1:8080/embed'),
        json={'revision': drive_index.MODEL_REVISION, 'dimensions': 768, 'embeddings': [[0.] * 768]})])
    monkeypatch.setattr(drive_index.httpx, 'post', post)
    assert len(drive_index.embed([{'kind': 'text', 'text': 'source'}])) == 1
    assert post.call_count == 2
    assert all(call.kwargs['timeout'] == 300 for call in post.call_args_list)
