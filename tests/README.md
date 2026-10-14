# Jarvis tests

All maintained test source lives here. From the repository root:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py
```

The command runs backend, real local embedding inference, Flutter UI/service, repeated offline agent workflow, harness-reporting and Android JVM unit tests. Embedding tests use `backend/models/embedding/.venv` and cached production weights by default; no running inference server is needed. See [local setup](../backend/models/embedding/README.md). Select one layer with `--suite backend`, `--suite embedding`, `--suite ui`, `--suite agent`, `--suite harness` or `--suite android`. Agent checks run three repetitions by default; change that with `--repeats 5`.

```text
tests/
  backend/                 # Python API, database, context and agent regressions
  embedding/               # Real model API, retrieval corpus and media checks
  android/
    ui/                    # Flutter widget/service tests and SQLite bridge
    kotlin/                # Native Android JVM unit tests
  harness/                 # Runner, benchmark selection and report-validation tests
  coding_agent_artifacts/  # Git-ignored experiments, fixtures, reports and evidence
  run.py
  README.md
```

Maintained tests and harness code are tracked in Git. The entire `tests/coding_agent_artifacts/` directory is ignored, excluded from pytest discovery, and may contain disposable generated files. Useful one-off scripts remain there; stable regressions belong in a maintained suite regardless of their author.

The runner uses the backend virtual environment except for local embedding tests, which use `backend/models/embedding/.venv` (override with `--embedding-python`). It executes Flutter from `mobile/` with an explicit `../tests/android/ui` path. Android Gradle sources point to `tests/android/kotlin`. Python discovery is configured in root `pytest.ini`. Existing dependency environments and SDKs remain with their applications; test dependencies must already be installed. Android tests need the Android SDK and a JDK; no phone is required.

Embedding tests load the production app/model locally with real repository documents and media bytes, validate the pinned model/revision and normalized 768-dimensional vectors, and check retrieval against labeled sources. They never replace inference with mocks. Normal local tests use cached weights offline. If local startup or resources are insufficient, explicitly opt into a service fallback; assertion failures do not trigger a remote rerun. See [the harness setup, authentication and report guide](harness/README.md).

```powershell
# Default: local environment, in-process production inference.
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding

# Optional: try the selected service only if local startup fails or times out.
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding --embedding-fallback-url https://YOUR-EMBEDDING-SERVICE.run.app
```

The backend, agent and harness Python suites use offline isolation. Embedding tests stay local by default; `--embedding-url` explicitly selects service-only execution and `--embedding-fallback-url` enables local-first fallback. The offline agent benchmark uses scripted provider responses and does not measure live model accuracy, token costs, billed SQLite record store reads or phone performance. Two satellite/provider probes remain opt-in `live` tests.

Check report handling alone with:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py --suite harness
```
