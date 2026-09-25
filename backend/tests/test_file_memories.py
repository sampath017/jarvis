import base64
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from src.api.routers import file_memories as files


MEMORY = {"id": "drive-id", "name": "receipt.pdf", "mimeType": "application/pdf", "storage": "cache",
          "caption": "My purchase", "url": "https://drive.google.com/file/d/drive-id/view",
          "size": 4, "account": "owner@example.com", "created_at": "2026-10-04T12:00:00Z"}


class Document:
    def __init__(self, store, name): self.store, self.name = store, name
    def set(self, value): self.store[self.name] = value
    def get(self): return SimpleNamespace(to_dict=lambda: self.store.get(self.name))


@pytest.fixture
def storage(monkeypatch):
    store = {}
    class Collection:
        def __init__(self, uid, kind): self.uid, self.kind = uid, kind
        def document(self, key): return Document(store, (self.uid, self.kind, key))
        def stream(self):
            return [SimpleNamespace(to_dict=lambda data=data: data) for (uid, kind, _), data in store.items()
                    if uid == self.uid and kind == self.kind]
    monkeypatch.setattr(files, "collection", lambda uid, kind="files": Collection(uid, kind))
    return store


def app():
    value = FastAPI()
    value.include_router(files.router)
    return value


def test_metadata_forbids_raw_file_fields():
    with pytest.raises(ValidationError): files.FileMemory(**MEMORY, raw="bytes")


@pytest.mark.parametrize("mime,part,model", [
    ("application/pdf", "file", files.OPENROUTER_MODEL_PDF),
    ("image/png", "image_url", files.OPENROUTER_MODEL_MULTIMODAL),
    ("video/mp4", "video_url", files.OPENROUTER_MODEL_MULTIMODAL),
])
def test_native_inputs_and_model_routing(mime, part, model):
    payload = files.native_payload({**MEMORY, "mimeType": mime}, "Summarize", b"data")
    assert payload["model"] == model
    assert payload["messages"][1]["content"][1]["type"] == part
    assert (payload.get("plugins") == [{"id": "file-parser", "pdf": {"engine": "native"}}]) == (mime == "application/pdf")


@pytest.mark.asyncio
async def test_metadata_is_private_and_contains_only_reference(storage):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        assert (await client.get("/file-memories")).status_code == 401
        headers = {"X-File-Memory-Session": "a" * 64}
        assert (await client.put("/file-memories/drive-id", json=MEMORY, headers=headers)).status_code == 200
        assert (await client.get("/file-memories", headers=headers)).json()["items"] == [MEMORY]
        assert (await client.get("/file-memories", headers={"X-File-Memory-Session": "b" * 64})).json()["items"] == []
        assert (await client.put("/file-memories/drive-id", json={**MEMORY, "raw": "data"}, headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_analysis_rejects_changed_bytes_before_provider_call(storage, monkeypatch):
    monkeypatch.setattr(files, "OPENROUTER_API_KEY", "test-key")
    headers = {"X-File-Memory-Session": "a" * 64, "X-Analysis-Question": base64.b64encode(b"What is the total?").decode()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        await client.put("/file-memories/drive-id", json=MEMORY, headers=headers)
        result = await client.post("/file-memories/drive-id/analyze?action_id=one", content=b"x", headers=headers)
        assert result.status_code == 422
        assert list(storage.values()) == [MEMORY]


def test_analysis_receipt_prevents_paid_replay(monkeypatch):
    from google.cloud import firestore
    monkeypatch.setattr(firestore, "transactional", lambda function: function)
    state = {}
    class Transaction:
        def set(self, ref, data): state.update(data)
    monkeypatch.setattr(files, "FirestoreService", lambda: SimpleNamespace(_db=SimpleNamespace(transaction=Transaction)))
    ref = SimpleNamespace(get=lambda **kwargs: SimpleNamespace(to_dict=lambda: state))
    assert files.claim_analysis(ref, "fingerprint") is None
    with pytest.raises(files.HTTPException) as duplicate: files.claim_analysis(ref, "fingerprint")
    assert duplicate.value.status_code == 409
    state.update(status="complete", result={"answer": "Saved answer"})
    assert files.claim_analysis(ref, "fingerprint") == {"answer": "Saved answer"}
    with pytest.raises(files.HTTPException): files.claim_analysis(ref, "changed-fingerprint")


@pytest.mark.asyncio
async def test_approved_analysis_persists_answer_without_raw_file(storage, monkeypatch):
    monkeypatch.setattr(files, "OPENROUTER_API_KEY", "test-key")
    calls = []
    class Provider:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "Total: 42"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
    monkeypatch.setattr(files, "httpx", SimpleNamespace(AsyncClient=Provider, HTTPError=httpx.HTTPError))
    monkeypatch.setattr(files, "claim_analysis", lambda ref, fingerprint: (ref.get().to_dict() or {}).get("result"))
    headers = {"X-File-Memory-Session": "a" * 64, "X-Analysis-Question": base64.b64encode(b"What is the total?").decode()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        await client.put("/file-memories/drive-id", json=MEMORY, headers=headers)
        for _ in range(2):
            response = await client.post("/file-memories/drive-id/analyze?action_id=one", content=b"data", headers=headers)
            assert response.status_code == 200
            assert response.json()["answer"] == "Total: 42"
    assert len(calls) == 1
    assert calls[0]["plugins"][0]["pdf"]["engine"] == "native"
    assert "file_data" not in str(storage) and "base64" not in str(storage)


@pytest.mark.asyncio
@pytest.mark.parametrize('finish_reason', ['length', 'error', 'content_filter'])
async def test_incomplete_native_answer_is_not_saved_as_success(storage, monkeypatch, finish_reason):
    monkeypatch.setattr(files, 'OPENROUTER_API_KEY', 'test-key')
    class Provider:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return httpx.Response(200, json={'choices': [{'finish_reason': finish_reason,
                'message': {'content': 'Partial experience answer'}}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    monkeypatch.setattr(files, 'httpx', SimpleNamespace(AsyncClient=Provider, HTTPError=httpx.HTTPError))
    monkeypatch.setattr(files, 'claim_analysis', lambda *_: None)
    headers = {'X-File-Memory-Session': 'c' * 64,
               'X-Analysis-Question': base64.b64encode(b'Experience and role?').decode()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url='http://test') as client:
        await client.put('/file-memories/drive-id', json=MEMORY, headers=headers)
        response = await client.post('/file-memories/drive-id/analyze?action_id=incomplete', content=b'data', headers=headers)
    assert response.status_code == 502
    assert 'complete answer' in response.json()['detail']
    assert all('result' not in record for record in storage.values())
