import json
from unittest.mock import Mock, patch

import pytest

from scripts.local_bulk_index import check_model, load_manifest, local_url
from src.services.drive_index import MODEL_REVISION


def test_bulk_mode_refuses_cloud_inference():
    for url in ('https://embedding.run.app', 'http://127.0.0.1.evil.test:8080',
                'http://user:password@localhost:8080', 'http://localhost:8080/embed'):
        with pytest.raises(ValueError):
            local_url(url)
    assert local_url('http://127.0.0.1:8080/') == 'http://127.0.0.1:8080'


def test_model_mismatch_is_rejected_before_indexing():
    response = Mock()
    response.json.return_value = {'ready': True, 'model': 'google/embeddinggemma-2',
                                  'revision': MODEL_REVISION, 'dimensions': 384}
    with patch('scripts.local_bulk_index.httpx.get', return_value=response):
        with pytest.raises(ValueError, match='compatible'):
            check_model('http://localhost:8080')
        response.json.return_value['dimensions'] = 768
        check_model('http://localhost:8080')


def test_manifest_requires_original_identity_and_rejects_duplicates(tmp_path):
    (tmp_path / 'file.txt').write_text('example')
    entry = {'owner': 'a' * 64, 'path': 'file.txt', 'memory': {
        'account': 'drive-account', 'id': 'drive-id', 'name': 'file.txt',
        'url': 'https://drive.google.com/file/d/drive-id/view',
        'mimeType': 'text/plain', 'source_version': '1'}}
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([entry]))
    assert load_manifest(manifest)[0][2] == tmp_path / 'file.txt'
    manifest.write_text(json.dumps([entry, entry]))
    with pytest.raises(ValueError, match='Duplicate'):
        load_manifest(manifest)
    entry['owner'] = 'jarvis_local_user'
    manifest.write_text(json.dumps([entry]))
    with pytest.raises(ValueError, match='owner hash'):
        load_manifest(manifest)
