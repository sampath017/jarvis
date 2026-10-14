"""Real local inference by default; an explicitly selected service is optional."""
import importlib.util
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import sys

import httpx
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]

# Read the production contract without starting or replacing its model loader.
spec = importlib.util.spec_from_file_location("embedding_contract", ROOT / "backend/models/embedding/app.py")
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)


def vectors_from(response, count):
    assert response.status_code == 200, f"Embedding HTTP {response.status_code}: {response.text[:500]}"
    body = response.json()
    assert body["model"] == contract.MODEL
    assert body["revision"] == contract.REVISION
    assert body["dimensions"] == 768
    vectors = np.asarray(body["embeddings"], dtype=float)
    assert vectors.shape == (count, 768)
    assert np.isfinite(vectors).all()
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-3)
    assert body["processing_ms"] >= 0
    return vectors


@pytest.fixture(scope="session")
def embedding_client():
    from harness.run import embedding_url

    origin = os.environ.get("JARVIS_TEST_EMBEDDING_URL")
    if not origin:
        # The normal TestClient lifespan invokes the production model loader.
        # Only HTTP dispatch is in-process: inference and FFprobe remain real.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("HF_HOME", str(ROOT / "backend/models/huggingface"))
        if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
            pytest.exit("Local embedding runtime unavailable: install FFmpeg and FFprobe on PATH; "
                        "see backend/models/embedding/README.md, or opt in to --embedding-fallback-url.", returncode=77)
        runtime = ExitStack()
        try:
            if os.name == "nt":
                runtime.enter_context(os.add_dll_directory(str(Path(shutil.which("ffmpeg")).parent)))
            from fastapi.testclient import TestClient
            client = runtime.enter_context(TestClient(contract.app))
        except (ImportError, OSError, MemoryError, RuntimeError) as exc:
            runtime.close()
            pytest.exit(f"Local embedding runtime unavailable ({type(exc).__name__}: {exc}). "
                        "Prepare backend/models/embedding/.venv and download the pinned weights using backend/models/embedding/README.md; "
                        "or opt in to --embedding-fallback-url.", returncode=77)
        try:
            yield client
        finally:
            runtime.close()
        return

    origin = embedding_url(origin)
    headers = {}
    token = os.environ.get("JARVIS_TEST_EMBEDDING_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=origin, headers=headers, timeout=180, trust_env=False) as client:
        try:
            response = client.get("/health")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            pytest.fail(
                f"Real embedding service unavailable at {origin} ({type(exc).__name__}). "
                "Start embedding/app.py using embedding/README.md or select --embedding-url; "
                "private services require JARVIS_TEST_EMBEDDING_TOKEN. No mocked fallback.",
                pytrace=False,
            )
        health = response.json()
        assert health["ready"] is True, "Embedding weights have not finished loading"
        assert (health["model"], health["revision"], health["dimensions"]) == (
            contract.MODEL, contract.REVISION, 768
        ), "Selected service does not match the production embedding contract"
        yield client


@pytest.fixture(scope="session")
def corpus():
    definition = json.loads((Path(__file__).parent / "retrieval_cases.json").read_text(encoding="utf-8"))
    for document in definition["documents"]:
        path = (ROOT / document["path"]).resolve()
        assert path.is_relative_to(ROOT)
        document["text"] = path.read_text(encoding="utf-8").split("\n## ", 1)[0][:6000]
        assert document["text"].strip()
    return definition


@pytest.fixture(scope="session")
def document_vectors(embedding_client, corpus):
    return vectors_from(embedding_client.post("/embed", json={
        "items": [{"text": document["text"]} for document in corpus["documents"]],
        "task": "document",
    }), len(corpus["documents"]))
