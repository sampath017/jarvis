# Jarvis verification harness

The harness runs the maintained test suites, repeats selected agent scenarios,
and writes one machine-readable result. Android UI tests live in
`tests/android/ui/`; native Android tests live in `tests/android/kotlin/`.
Embedding checks use real inference. The agent workflow benchmark uses scripted
provider responses and has a separate purpose.

## Run it

From the repository root, after preparing the local embedding environment once:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py
```

| Selection | What executes | Prerequisites |
| --- | --- | --- |
| `--suite backend` | `tests/backend/`, excluding opt-in `live` probes | Backend virtual environment and dev dependencies |
| `--suite embedding` | `tests/embedding/`, loading the production app/model locally | `backend/models/embedding/.venv`, cached weights and FFmpeg; optional service fallback |
| `--suite ui` | Flutter widget/service tests in `tests/android/ui/` | Flutter and installed `mobile/` packages |
| `--suite android` | Native JVM tests in `tests/android/kotlin/` | Android SDK, Gradle dependencies and JDK |
| `--suite agent` | Selectors in `agent_cases.json`, repeated three times by default | Backend test environment |
| `--suite harness` | Report parsing, inference configuration and result aggregation tests | Backend test environment |
| `--suite all` (default) | Backend, embedding, UI, agent, harness, then native Android | All of the above |

```powershell
# Repeated agent regressions; no external provider calls.
./backend/.venv/Scripts/python.exe tests/run.py --suite agent --repeats 5

# UI remains inside the Android test tree.
./backend/.venv/Scripts/python.exe tests/run.py --suite ui

# Increase the per-process deadline for a slow model or build.
./backend/.venv/Scripts/python.exe tests/run.py --timeout 1200
```

`--repeats` accepts 1–20 and affects only the agent benchmark. `--timeout`
defaults to 900 seconds per suite process, or per agent repetition. Supply
`--flutter C:/path/to/flutter.bat` if Flutter is absent from PATH. The harness
prefers `backend/.venv/` Python and otherwise uses the launching interpreter.
Local embedding tests use their separate `backend/models/embedding/.venv` interpreter.
It does not install dependencies, deploy services or install an APK. No phone
is needed for the widget/service and JVM suites.

## Real embedding setup and inputs

Prepare the CPU environment and cache using
[backend/models/embedding/README.md](../../backend/models/embedding/README.md). The default run loads the pinned
production model in `backend/models/embedding/.venv`, starts the real FastAPI lifespan in-process,
and exercises its routes through TestClient. No listening server or Docker is
required. FFprobe and the model encoder still execute normally.

```powershell
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding

# Select another prepared local environment if needed.
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding --embedding-python C:/path/to/python.exe

# Optional local-first fallback for insufficient local resources/startup failures.
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding --embedding-fallback-url https://YOUR-EMBEDDING-SERVICE.run.app
```

Local tests use cached weights with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. Setup downloads happen explicitly, outside the test run.
The default model cache is
`backend/models/huggingface/`; set `HF_HOME` consistently
for setup and tests to use another cache. A project-local FFmpeg shared build
can live in `tests/coding_agent_artifacts/embedding/ffmpeg/bin/`, or use PATH.

Without an explicit fallback, unavailable local dependencies/weights fail with
exit 77. With `--embedding-fallback-url`, local startup/preflight failures or a
suite timeout can trigger a service attempt. A successful local run makes no
fallback request. Ordinary assertion failures never trigger a remote rerun.
Reports preserve both attempts and the selected runtime. Each attempt has its
own `--timeout` budget, so a fallback can extend the total run duration.

`--embedding-url` (or explicit `JARVIS_TEST_EMBEDDING_URL`) selects service-only
execution using the backend environment and bypasses local weights. For example,
pass `--embedding-url http://127.0.0.1:8080` to test a running local container.
Direct service selection and fallback selection are mutually exclusive. Remote
origins require HTTPS; credentials, query strings and paths are rejected. The
runner does not infer a destination from the backend's private `.env` file.

For an authorized private Cloud Run endpoint, put a valid IAM identity token in
`JARVIS_TEST_EMBEDDING_TOKEN` and pass its origin:

```powershell
$env:JARVIS_TEST_EMBEDDING_TOKEN = (& gcloud.cmd auth print-identity-token --quiet)
./backend/.venv/Scripts/python.exe tests/run.py --suite embedding --embedding-url https://YOUR-EMBEDDING-SERVICE.run.app
Remove-Item Env:JARVIS_TEST_EMBEDDING_TOKEN
```

The identity must have invoke access and the token must be accepted by the
service. Tokens go in the Authorization header, not command arguments or reports.
Remote runs upload the test inputs and can incur service usage. Choose the
destination deliberately. Each service HTTP request has a 180-second timeout,
including the initial health request during a possible cold start. To use the
same authentication for local-first fallback, replace `--embedding-url` in the
example with `--embedding-fallback-url`. Tokens are removed from the local child
process environment and passed only to a selected service attempt.

`tests/embedding/retrieval_cases.json` defines four source documents and four
labeled questions. Tests read each source from the current checkout, taking its
introductory section before the first `##` heading, capped at 6,000 characters.
These are actual Jarvis documents about bulk embeddings, notes, Calendar and
runtime power. They contain no exported personal chats or Drive originals.
The suite performs these checks:

1. `/health` must report loaded weights, the production model
   `google/embeddinggemma-2`, revision
   `914f7f89142e33e77833254d9c9b90c3cef7303b` (or the production
   `MODEL_REVISION` environment override), and 768 dimensions.
2. Batched document embeddings and query embeddings must be finite and unit
   normalized. Each labeled query must rank its expected source first by cosine
   similarity. Reports preserve rank, recall@1, reciprocal rank, source path,
   SHA-256 of the exact text sent, and service processing time.
3. Repeated inputs must produce consistent vectors; query and document tasks
   must produce different encodings. Two concurrent real requests must complete
   successfully and yield distinct vectors for distinct inputs. This does not
   prove that the server scheduled both in parallel.
4. The checked-in Android launcher PNG must produce a valid image embedding.
   Actual generated PCM WAVs check the accepted 30.0004375-second rounding case
   and rejected 30.02-second case. The service runs FFprobe itself. Silence is
   a generated boundary fixture, not a recording or an audio-retrieval benchmark.
5. Malformed image data, empty text/batches and an invalid task must return 422.

Local mode dispatches through the real ASGI app in-process; service mode uses
HTTP. Neither mode mocks the encoder or FFprobe. Wrong weights, invalid vectors
or failed retrieval assertions fail the run; there is no mocked fallback or
silent skip. Unavailable local startup/deadlines can use the explicitly selected
real service fallback described above. The suite currently checks text, image and
audio; video inference remains covered by the image build's smoke check.
Retrieval scores describe this small repository corpus, not general model
quality or live conversational-agent reasoning.

## What lives in harness/

| File | Responsibility |
| --- | --- |
| `run.py` | CLI, subprocess execution, suite selection, deadlines, result parsing, repeated agent aggregation and JSON reports |
| `offline.py` | Pytest plugin injecting real isolated in-memory SQLite repositories and blocking non-loopback sockets for backend, agent and harness suites |
| `check_embedding_runtime.py` | Local dependency/media-tool preflight, including before pytest is installed |
| `agent_cases.json` | Stable scenario IDs, purpose descriptions and pytest node selectors |
| `test_reporting.py` | Failure/skip/property preservation, empty suites and incomplete Flutter reports |
| `test_embedding_config.py` | Local environment selection, opt-in fallback rules, service origin validation and measured retrieval aggregation |
| `test_process_timeout.py` | A timed-out process and its child workers stop before a fallback can start |
| `__init__.py` | Allows the root `tests/run.py` entry point to import the harness |

For each selected suite, the runner prepares isolated fixture paths, executes the
suite, parses its report, and saves the result before continuing. Backend, agent
and harness tests receive explicit isolated SQLite repository handles from the
offline plugin; production has no implicit server database fallback.
Failures do not stop later suites from producing evidence. A nonzero exit,
timeout, invalid/missing report, empty suite or entirely skipped suite fails the
run. A timeout attempts to stop the process tree, including local inference
workers. Service fallback is blocked if process-tree cleanup cannot be confirmed
(for example, under restricted Windows process permissions). Mixed passed/skipped
tests are allowed if no test failed. The final process
exit is zero only when every selected suite passes.

Flutter runs from `mobile/` with the explicit `tests/android/ui/` path, so its
package configuration stays with the app. The SQLite bridge remains beside the
Flutter tests in `ui/support/`. Gradle runs from `mobile/android/` and its test
source set reads `tests/android/kotlin/`. Compiled output stays in the ignored
mobile build directory. Gradle may reuse cached native results when inputs are
unchanged; these timings are not agent performance measurements.

## Agent workflow scenarios and isolation

`agent_cases.json` selects existing tests of the production graph, nodes, tools
and local persistence. Parameterized selectors can produce multiple test cases.
Coverage includes greeting routing, shared chat/background agent invocations,
complete current-chat history, file follow-ups, complete replies, partial tool arguments, provider
errors, write deduplication, declined writes, merge source preservation, deletion
after review, one-use approval grants and query-cost guards.

Every repetition runs in a fresh pytest process. Three graph tests also record
scripted model-call counts, graph steps, tool-result counts or saved-row counts.
Per-case p50/p95 uses nearest-rank percentiles across repetitions. With the
default three repetitions these are regression indicators, not a latency study.

For backend, agent and harness suites, the runner sets dummy model credentials,
disables tracing and loads `offline.py`. Plugin autoload is disabled and
`pytest_asyncio.plugin` is loaded explicitly. The plugin injects real isolated
SQLite repositories; provider responses and platform boundaries may be scripted.
Loopback remains available for local API checks. This is test isolation, not an operating-system sandbox. The real
embedding suite intentionally does not load the backend's offline socket plugin.
Local mode loads cached weights with offline flags and uses in-process ASGI
dispatch. Service mode calls the explicitly selected inference origin.

The agent benchmark reports mode `offline-scripted-provider`. It checks workflow
behavior under controlled provider outputs, not live LLM accuracy, provider
latency/token cost, phone battery/frame rate or billed SQLite record store reads. UI tests
also remain widget/service checks with simulated platform boundaries.

Two existing satellite/provider probes remain separately opt-in:

```powershell
./backend/.venv/Scripts/python.exe -m pytest -m live tests/backend/test_agent_satellite_chat.py tests/backend/test_satellite_vision.py
```

Those probes need actual provider credentials and make external calls. The
`live` marker refers to these optional probes; real embedding inference is a
required suite in the normal full harness run.

## Verified SQL checkout

On 28 October 2026, all 542 backend cases across 63 files passed (two live probes deselected). The combined backend/harness run had 555 passes and one intermittent Windows timeout cleanup check failure; the separate harness rerun passed all 14 cases and nine subtests. Evidence: `tests/coding_agent_artifacts/harness/pure-sql-verified.xml` and `pure-sql-harness.xml` with matching logs. Full Flutter verification passed 172 tests; native JVM verification passed 43; final installed Android instrumentation passed seven isolated SQLite cases. These checks do not establish live LLM accuracy or real embedding-model performance.

## Reports and troubleshooting

Output is Git-ignored under `tests/coding_agent_artifacts/harness/`, with no date
or local subfolder:

| Artifact | Contents |
| --- | --- |
| `latest.json` | Schema version, start time, selected suites, per-suite results and overall `passed` |
| `<suite>.json` | Most recent result for that suite; unselected suite files may be older |
| `<suite>.log` | Combined subprocess output; agent repetitions append to one log |
| `<suite>.xml` | Pytest JUnit cases, statuses, call times and measured properties; agent XML is the final repetition |
| `android-results/*.xml` | Copied native Gradle JUnit results |
| `embedding-local.log` / `.xml` | Preserved local evidence when an optional service fallback runs |

All suite JSON preserves individual cases and counts. Embedding JSON reports
mode `real-model-inference`, `runtime` (`local` or `service`), the Python
interpreter, endpoint (null for in-process inference), model provenance, and
`inference.retrieval` with query count, mean recall@1, mean reciprocal rank and
source hashes. No measured queries means null scores, never an assumed perfect
score. When fallback runs, `fallback_used` is true and `attempts` retains the
failed local result followed by the service result; suite success then reflects
the service result. Without fallback, the local result is authoritative.
Read `passed` and counts alongside scores: a partial failed run can still
contain some successful measurements. Agent JSON retains every repetition and
per-scenario timing and recorded metrics. Pytest timings exclude fixture setup
and teardown; model loading or document-vector fixture time therefore appears
in suite wall time rather than each test's call time. Service `processing_ms`
excludes network transit; Flutter timings do not measure phone frame delivery.

Generated pytest inputs live under
`tests/coding_agent_artifacts/tests/fixtures/harness/` and may be overwritten.
Maintained tests, corpora and harness code belong in the regular tracked suites.

If a run fails, inspect its `<suite>.log` and JSON `error`/failed cases. For an
embedding setup failure check the local preflight log, cached weights and FFmpeg.
For optional service execution also check `/health`, the pinned revision and IAM access.
For UI failures check Flutter and installed packages; for native failures check
the SDK/JDK and Gradle output. To check report handling without starting a model:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py --suite harness
```
