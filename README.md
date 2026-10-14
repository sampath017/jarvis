# Jarvis — Android personal assistant

Jarvis is an Android Flutter app for chat, notes, reminders, recordings, app usage
and location-aware context. The Python FastAPI/LangGraph API supplies optional
AI and Google integrations. Android is the only client platform.

## Storage

- **Phone:** `jarvis_mobile.db` (SQLite with WAL), native telemetry SQLite, private
  recording files, and Android preferences. Recording names and archive choices
  work offline. Local alarms deliver scheduled reminders without Firebase.
- **API:** request-scoped RAM for app records, with changes committed by Android.
  No Firebase/Firestore SDK, FCM, persistent server chat database or backup.
- **Chroma:** existing cloud settings and collection retained for document chunks,
  embeddings and semantic retrieval. SQLite does not replace the document index.
- **Google Drive/Calendar:** phone-authorized search, calendar actions and explicit
  file saves. Ordinary attachments stay on the phone; there is no backup/export.

Cloud Run's filesystem is lost when an instance stops. Server-side OAuth sessions,
index jobs, command receipts, context history and AI allowance records stored there
are also temporary. Use a local API on persistent disk for durable server features.
Per-instance spending limits do not provide a project-wide budget across restarts
or replicas. Cloud Run/embedding/LLM/Maps usage can still incur compute/API charges.
See [storage decisions and migration limits](docs/android-local-storage.md).

## Repository

```text
mobile/       Flutter UI and native Android services
backend/      FastAPI, agents, SQLite repositories, optional embedding compute
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
recordings do not require Firebase or a Google sign-in. AI requests require a
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
