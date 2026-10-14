# Local models and embedding microservice

Project model weights, download metadata, and the local embedding microservice live here:
- Model weights: The default Hugging Face cache is `backend/models/huggingface/`, including the pinned production EmbeddingGemma checkpoint. Model weights are Git-ignored.
- Embedding microservice: The standalone embedding service and local runner live in `backend/models/embedding/`.

Prepare the weights with `backend/models/embedding/.venv/Scripts/python.exe backend/models/embedding/prepare_test_model.py`
from the repository root. Normal embedding tests use this cache offline.
Set `HF_HOME` consistently during setup and tests to override the location.

Python environments remain in `backend/models/embedding/.venv/`; generated reports and media
tools remain under `tests/coding_agent_artifacts/`.
