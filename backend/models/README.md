# Local models and embedding microservice

Hands-free voice uses the Apache-2.0 Vosk small English model under `backend/models/voice/`. The Android build packages only `backend/models/voice/android/` as native assets. Weights, downloaded archives and their cache stay ignored; model metadata records the official source URL and SHA-256 locally. See `docs/voice-mode.md` for setup and the opt-in microphone lifecycle.

Project model weights, download metadata, and the local embedding microservice live here:
- Model weights: The default Hugging Face cache is `backend/models/huggingface/`, including the pinned production EmbeddingGemma checkpoint. Model weights are Git-ignored.
- Embedding microservice: The standalone embedding service and local runner live in `backend/models/embedding/`.

Prepare the weights with `backend/models/embedding/.venv/Scripts/python.exe backend/models/embedding/prepare_test_model.py`
from the repository root. Normal embedding tests use this cache offline.
Set `HF_HOME` consistently during setup and tests to override the location.

Python environments remain in `backend/models/embedding/.venv/`; generated reports and media
tools remain under `tests/coding_agent_artifacts/`.

Voice endpointing uses Silero VAD v5.1 (MIT), from `https://raw.githubusercontent.com/snakers4/silero-vad/v5.1/src/silero_vad/data/silero_vad.onnx`, stored in ignored `backend/models/voice/android/vad/silero_vad.onnx`. SHA256: `2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f`. The upstream MIT LICENSE is bundled alongside it. Android runs it with ONNX Runtime 1.20.0.
