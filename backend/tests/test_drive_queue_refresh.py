from unittest.mock import Mock
from src.services import drive_index_queue as queue


def test_older_queued_export_is_refreshed_only_for_requested_owner_and_file(monkeypatch):
    memory = {'id': 'sheet', 'account': 'owner@example.invalid', 'mimeType': 'application/vnd.google-apps.spreadsheet', 'source_version': '7'}
    requested = queue.identity('owner-a', memory)
    other = queue.identity('owner-b', memory)
    refs = {requested: Mock(), other: Mock()}
    refs[requested].get.return_value.to_dict.return_value = {'status': 'queued', 'memory': {'mimeType': 'application/pdf'}}
    store = Mock()
    store.document.side_effect = lambda key: refs[key]
    bucket = Mock()
    bucket.blob.return_value.create_resumable_upload_session.return_value = 'https://storage.googleapis.com/synthetic'
    monkeypatch.setattr(queue, 'jobs', lambda: store)
    monkeypatch.setattr(queue, 'bucket', lambda: bucket)
    result = queue.begin('owner-a', memory)
    assert result['upload_required'] is True
    refs[requested].set.assert_called_once()
    refs[other].set.assert_not_called()
    assert refs[requested].set.call_args.args[0]['owner'] == 'owner-a'
