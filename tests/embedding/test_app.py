"""Exercise production inference over repository documents and actual media bytes."""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import hashlib
import json
from pathlib import Path
import wave

import numpy as np
import pytest

from conftest import ROOT, vectors_from

QUERIES = json.loads((Path(__file__).parent / "retrieval_cases.json").read_text(encoding="utf-8"))["queries"]


def test_health_reports_loaded_production_model(embedding_client, record_property):
    health = embedding_client.get("/health").json()
    assert health["ready"] is True
    assert health["model_load_seconds"] >= 0
    for key in ("model", "revision", "dimensions", "device", "model_load_seconds"):
        record_property(key, health[key])


@pytest.mark.parametrize("query", QUERIES, ids=[query["id"] for query in QUERIES])
def test_real_documents_rank_expected_source_first(embedding_client, corpus, document_vectors, query, record_property):
    response = embedding_client.post("/embed", json={"items": [{"text": query["text"]}], "task": "query"})
    vector = vectors_from(response, 1)[0]
    scores = document_vectors @ vector
    ranking = np.argsort(-scores).tolist()
    expected = next(index for index, document in enumerate(corpus["documents"]) if document["id"] == query["expected"])
    rank = ranking.index(expected) + 1
    record_property("source", corpus["documents"][expected]["path"])
    record_property("source_sha256", hashlib.sha256(corpus["documents"][expected]["text"].encode("utf-8")).hexdigest())
    record_property("corpus_documents", len(corpus["documents"]))
    record_property("expected_rank", rank)
    record_property("recall_at_1", int(rank == 1))
    record_property("reciprocal_rank", 1 / rank)
    record_property("processing_ms", response.json()["processing_ms"])
    assert rank == 1, f"Expected {query['expected']}; ranked {[corpus['documents'][i]['id'] for i in ranking]}"


def test_real_vectors_are_repeatable_and_task_specific(embedding_client, corpus):
    text = corpus["queries"][0]["text"]
    query = {"items": [{"text": text}], "task": "query"}
    first = vectors_from(embedding_client.post("/embed", json=query), 1)
    second = vectors_from(embedding_client.post("/embed", json=query), 1)
    document = vectors_from(embedding_client.post("/embed", json={**query, "task": "document"}), 1)
    np.testing.assert_allclose(first, second, atol=1e-5)
    assert not np.allclose(first, document, atol=1e-4), "Query/document prefixes must change the real encoding"


def test_two_real_inference_requests_complete(embedding_client, corpus):
    def request(query):
        return vectors_from(embedding_client.post("/embed", json={
            "items": [{"text": query["text"]}], "task": "query",
        }), 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        vectors = list(pool.map(request, corpus["queries"][:2]))
    assert not np.allclose(vectors[0], vectors[1])


def test_real_image_asset_produces_normalized_vector(embedding_client):
    image = ROOT / "mobile/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"
    response = embedding_client.post("/embed", json={"items": [{
        "kind": "image", "data": base64.b64encode(image.read_bytes()).decode("ascii"),
    }]})
    vectors_from(response, 1)


@pytest.mark.parametrize("samples,status", [(480007, 200), (480320, 422)])
def test_real_audio_probe_respects_sample_rounding(embedding_client, samples, status):
    # Actual PCM WAV at 16 kHz: 30.0004375 s or 30.02 s. The service runs
    # ffprobe and the encoder itself; silence is a generated boundary fixture.
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(samples * 2))
    response = embedding_client.post("/embed", json={"items": [{
        "kind": "audio", "data": base64.b64encode(stream.getvalue()).decode("ascii"),
    }]})
    assert response.status_code == status
    if status == 200:
        vectors_from(response, 1)


@pytest.mark.parametrize("payload", [
    {"items": [{"kind": "image", "data": "not-base64"}]},
    {"items": [{"text": "   "}]},
    {"items": []},
    {"items": [{"text": "hello"}], "task": "unknown"},
])
def test_invalid_input_is_rejected_by_real_service(embedding_client, payload):
    assert embedding_client.post("/embed", json=payload).status_code == 422
