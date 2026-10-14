# Jarvis — Android personal assistant

Jarvis is an Android Flutter app for chat, notes, reminders, recordings, app usage
and location-aware context. The Python FastAPI/LangGraph API supplies optional
AI and Google integrations. Android is the only client platform.

Chat and ambiguous context events use one agent runtime with independent
invocations. Background assessments have restricted evidence tools and validated
structured output. Android sensing, journey reducers and reminder delivery stay
deterministic and continue without a model when the evidence is sufficient.
See [the architecture guide](docs/codebase-architecture.md).

## Storage

- **Phone:** `jarvis_mobile.db` (SQLite with WAL), native telemetry SQLite,
  recording files, and Android preferences. Recording names and archive choices
  work offline. Local alarms deliver scheduled reminders without a cloud request.
- **API:** request-scoped RAM for app records, with changes committed by Android.
  The production API keeps no persistent server chat database or app-record backup.
- **Chroma:** existing cloud settings and collection retained for document chunks,
  embeddings and semantic retrieval. SQLite does not replace the document index.
- **Google Drive/Calendar:** phone-authorized search, calendar actions and explicit
  file saves. A weekly phone-owned database backup updates one file at
  `Jarvis/jarvis_db_backup.db`; ordinary attachment originals stay on the phone.
  See [weekly backup](docs/weekly-database-backup.md).

Active command coordination and completed-response delivery windows exist in API
process memory. An API restart can end a request while the phone retains its data.
Phone-supplied AI accounting is not a project-wide billing cap across resets or
replicas. Cloud Run, embedding, model and Maps usage can still incur service costs.
See [storage ownership and limits](docs/android-local-storage.md).

The current application uses named SQL entity tables throughout. The phone
conversion verified all 2,244 existing rows and preserved reminders before the old
generic tables, temporary migration copies and compatibility readers were removed.
Only the converted SQL records remain; the application has no document-style
storage adapter or alternate server-record mode.

## Repository

```text
mobile/       Flutter UI and native Android services
backend/      FastAPI, shared agent runtime, SQLite repositories, optional embedding compute
backend/models/  Local model cache and embedding runtime
tests/       Backend, Flutter, native Android, embedding and harness suites
docs/        Current storage guide and dated historical engineering notes
```

## Run

```powershell
cd backend
uv sync
# Copy .env.example to .env and configure optional API keys.
uv run backend
```

```powershell
cd mobile
flutter pub get
flutter run -d <android-device-id>
```

Select the API URL in Android Settings. Local notes, reminders, app usage and
recordings work locally without Google sign-in. AI requests require a
reachable API and the configured model provider.

## Verify

From the repository root:

```powershell
./backend/.venv/Scripts/python.exe tests/run.py --suite backend
./backend/.venv/Scripts/python.exe tests/run.py --suite ui
./backend/.venv/Scripts/python.exe tests/run.py --suite android
```

See [the test guide](tests/README.md) for real local embedding checks and other suites.

Internal development — all rights reserved.
