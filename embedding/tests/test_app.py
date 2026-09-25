import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor
import threading
import base64
import json
import pytest
import numpy as np
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('embedding_app', Path(__file__).parents[1] / 'app.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_query_uses_retrieval_prefix_and_model_revision():
    module.model = Mock()
    module.model.encode.return_value = np.zeros(768)
    client = TestClient(module.app)
    result = client.post('/embed', json={'items': [{'text': 'find receipt'}], 'task': 'query'})
    assert result.status_code == 200
    assert result.json()['revision'] == module.REVISION
    module.model.encode.assert_called_once_with('task: search result | query: find receipt', normalize_embeddings=True)


def test_bad_image_is_rejected_before_inference():
    module.model = Mock()
    result = TestClient(module.app).post('/embed', json={'items': [{'kind': 'image', 'data': 'not-base64'}]})
    assert result.status_code == 422
    module.model.encode.assert_not_called()


def test_two_requests_execute_in_parallel():
    barrier = threading.Barrier(2)
    def encode(*args, **kwargs):
        barrier.wait(timeout=3)
        return np.zeros(768)
    module.model = Mock()
    module.model.encode.side_effect = encode
    def request():
        return TestClient(module.app).post('/embed', json={'items': [{'text': 'parallel test'}]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request(), range(2)))
    assert all(result.status_code == 200 for result in results)


@pytest.mark.parametrize('duration,status', [(30.000438, 200), (30.02, 422)])
def test_audio_cut_allows_sample_rounding_but_rejects_longer_clips(monkeypatch, duration, status):
    module.model = Mock()
    module.model.encode.return_value = np.zeros(768)
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: Mock(stdout=json.dumps({'format': {'duration': str(duration)}})))
    response = TestClient(module.app).post('/embed', json={'items': [{'kind': 'audio', 'data': base64.b64encode(b'synthetic audio').decode()}]})
    assert response.status_code == status
    assert module.model.encode.called == (status == 200)
