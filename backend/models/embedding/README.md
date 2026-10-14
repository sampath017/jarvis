# Bulk indexing locally, runtime inference in Cloud Run

For future large imports, run both file extraction/chunking and embedding
inference locally, then upload vectors to the existing Chroma collection.
Use Cloud Run for query embeddings and small incremental updates. Avoid a Cloud
Run index job for the same bulk import: the worker's CPU and memory remain
billable while it waits for the embedding service.

Keep the existing model contract:

- Model: `google/embeddinggemma-2`
- Revision: `914f7f89142e33e77833254d9c9b90c3cef7303b`
- 768 dimensions, normalized vectors, cosine distance
- Collection: `jarvis-drive-eg2-768-v1`
- Query prefix: `task: search result | query: `
- Document prefix: `title: none | text: `

Run the existing `backend/models/embedding/app.py` locally so prefixes, media processing, model
revision and normalization match production. A different model requires a
separate collection and reindexing.

## Local test environment (default)

Prepare a dedicated CPU environment from the repository root. These setup steps
download dependencies and the pinned model once; normal tests use the cache offline.

```powershell
uv venv backend/models/embedding/.venv --python backend/.venv/Scripts/python.exe
uv pip install --python backend/models/embedding/.venv/Scripts/python.exe torch==2.14.1 torchvision==0.29.1 torchcodec==0.17.0 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python backend/models/embedding/.venv/Scripts/python.exe -r backend/models/embedding/requirements-test.txt
./backend/models/embedding/.venv/Scripts/python.exe backend/models/embedding/prepare_test_model.py
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding
```

On Linux/macOS use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.
The test environment is separate from the backend environment. The harness
starts the production FastAPI lifespan inside the test process, loading the same
CPU model and revision; no Docker or listening server is needed. Use
`--embedding-python` to select another prepared interpreter.

Install FFmpeg with `ffmpeg` and `ffprobe` on PATH. Windows audio decoding needs
a **shared** FFmpeg build, including its DLLs; see the
[FFmpeg download links](https://ffmpeg.org/download.html) and
[TorchCodec installation guide](https://github.com/meta-pytorch/torchcodec#installing-torchcodec).
Alternatively place its binaries/DLLs in
`tests/coding_agent_artifacts/embedding/ffmpeg/bin/`; the harness adds this local
directory to the child process's PATH. It does not change the system PATH.

Weights default to the `backend/models/huggingface/` directory.
Set `HF_HOME` consistently for setup and tests to use a different cache. Local
tests set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; missing weights or
runtime dependencies produce an explicit setup failure, never mocked vectors.

If the local machine cannot initialize the model or exceeds the suite deadline,
an explicitly selected service can be used as a fallback:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding --embedding-fallback-url https://YOUR-EMBEDDING-SERVICE.run.app
```

Set `JARVIS_TEST_EMBEDDING_TOKEN` for a private service. A healthy local run never
contacts the fallback. Assertion failures do not trigger it. Reports retain the
local attempt and identify service fallback use. `--embedding-url` selects a
service directly when desired. See the [harness guide](../tests/harness/README.md).

## Start a local inference service (optional)

From the repository root, with Docker Desktop available:

```powershell
docker build -t jarvis-embedding-local ./embedding
docker run --rm -p 127.0.0.1:8080:8080 jarvis-embedding-local
```

This downloads the pinned model once into a local image and includes CPU
PyTorch and FFmpeg. It does not run Cloud Build. Check
`http://127.0.0.1:8080/health` after model loading completes. Local hardware
determines throughput; Chroma storage/writes and data transfer can still cost.

## Verify a running service (optional)

To verify the running model with real inputs before indexing, run from the
repository root:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding --embedding-url http://127.0.0.1:8080
```

This checks real query/document vectors and retrieval over checked-in Jarvis
documentation, the Android launcher image, and actual WAV duration boundaries.
It uses the service's encoder and FFprobe without inference mocks. Model
identity, revision, normalization and dimensions must match the contract above.
The [harness guide](../tests/harness/README.md) explains remote authentication,
recorded corpus hashes and report interpretation.

## Prepare and run the local worker

Download/export authorized Drive originals. Use the same exported formats as
the phone importer: DOCX, XLSX, PPTX or PNG for native Google documents; set
`mimeType` to the exported format. Keep original Drive IDs, account, source
versions and URLs. Use the existing file-memory owner hash from the local SQLite file-memory records
`file_memories/{owner}`; this is not the chat user ID or an account email.

Create a private JSON manifest in a git-ignored `.tmp*` directory. Paths are
relative to the manifest, or absolute:

```json
[
  {
    "owner": "<existing 64-character lowercase hexadecimal owner hash>",
    "path": "exports/example.pdf",
    "memory": {
      "account": "<original Drive account>",
      "id": "<original Drive file ID>",
      "name": "example.pdf",
      "mimeType": "application/pdf",
      "url": "https://drive.google.com/file/d/<original Drive file ID>/view",
      "source_version": "<original Drive version>"
    }
  }
]
```

Vectors are saved in the local Chroma index next to the API SQLite database.
Keep credentials out of the manifest. From `backend`:

```powershell
.venv/Scripts/python.exe -m scripts.local_bulk_index ../.tmp-bulk/manifest.json
.venv/Scripts/python.exe -m scripts.local_bulk_index ../.tmp-bulk/manifest.json --apply
```

The first command validates files without network calls. The second checks the
local model before writing vectors and refuses remote inference endpoints. It
reuses production readers, batching, owner metadata and digest checks. Completed
unchanged files skip inference on rerun. A failed file retains its previous
completed generation; retrying may recompute that incomplete file.

This worker writes Chroma vectors directly. It does not register new file
memories, update phone indexing jobs or launch Cloud Run. Use the original file
metadata registered under the same owner. New files also need metadata in the
phone's authorized Drive catalog. Avoid simultaneously submitting the same
files through the phone's bulk scanner, which still uses the ordinary cloud
queue. Cloud runtime queries retain their existing `EMBEDDING_URL` and can use
these compatible vectors immediately.

## Cost finding on October 9, 2026

The supplied screenshot shows ₹256.79 net service cost, including ₹185.75 Cloud
Run after ₹501.06 savings (₹686.82 usage cost). Cloud Build is ₹44.95 and
Artifact Registry is ₹17.21.

Monitoring for October 1–9 showed approximately 47.50 vCPU-hours for the Mumbai
embedding service, 24.50 for the index worker and 3.05 for the backend. Including
earlier embedding services, indexing represents about 96% of recorded CPU
allocation. This indicates bulk indexing drove the spike; it is not an exact
rupee allocation because memory, billing mode and credits differ. The latest
successful index execution ran approximately 9 hours 10 minutes.

Both current services use request billing with no configured minimum instance
count. Keep this setting for runtime use. Backend availability and phone event
wakeups do not require a continuously running embedding container. Batch tested
changes into fewer deployments to reduce build and image storage overhead.
No bulk reindex was launched during this investigation.

Sources: [Cloud Run pricing](https://cloud.google.com/run/pricing) and
[billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings).
