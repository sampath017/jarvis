# Jarvis Android processing API

FastAPI/LangGraph processes Android commands and context events. Run `uv sync` and
`uv run backend`. Android owns durable app records; every API computation uses a request-scoped SQL workspace.

`graph/nodes/agent.py` and `agent_tools.py` provide the shared runtime for chat
and optional background context assessment. Each invocation has independent
scratch messages and budgets. Context assessments expose read-only evidence tools
and return a validated `ContextAssessment`; chat tools retain their existing
runtime action controls. Deterministic context reducers and Android reminder
execution do not depend on an extra model turn.

Set `LLM_MODEL` in `backend/.env` to select the model for both invocation types.
`LLM_OUTPUT_TOKENS` controls chat output capacity; background assessments use
their smaller runtime budget. `backend/.env.example` contains the same settings.

App records exist only in request-scoped RAM workspaces and return as changes for
Android SQLite. Persistent server chat storage, cloud OAuth sessions, background
jobs, backups and record-sync endpoints are absent from the production API.
Tracing and user-content file logging are disabled.

The existing Chroma Cloud document index and embedding compute service remain:
configure the existing `CHROMA_HOST`, `CHROMA_API_KEY`, `CHROMA_TENANT`,
`CHROMA_DATABASE`, and `EMBEDDING_URL` values. Document chunks and vectors stay in
Chroma. File sources are processed temporarily; no bucket staging is required.

`services/sqlite_store.py` supplies named SQL entities, parameterized queries and
transactions. `RecordStore` exposes domain operations over those repositories;
`MobileScope` imports bounded phone state and returns explicit row changes.
Scalar fields use SQL columns and nested values use JSON columns. Tests exercise
the same repositories with explicit isolated SQL handles.

The one-time phone conversion verified all 2,244 existing rows and preserved
reminders. Old generic tables, migration archives, compatibility readers and
conversion code were then removed. There is no alternate server-storage mode or
document-style storage adapter in the final backend.

Offline application verification passed all **542 backend cases across 63 files**, with two live probes deselected. A separate harness run passed **14 cases and nine subtests**. The combined run first encountered an intermittent Windows process-timeout cleanup check failure; it passed on the isolated harness rerun. Evidence is `tests/coding_agent_artifacts/harness/pure-sql-verified.xml` and `pure-sql-harness.xml` with their logs.
Android verification confirmed all 2,244 converted rows, removal of all five
retired tables, unchanged values in 34 protected tables and a native SQLite
integrity result of `ok`; see
`tests/coding_agent_artifacts/diagnostics/sql-final-cleanup-verification.json`
and `phone-sql-native-integrity.log`.

See [the storage guide](../docs/android-local-storage.md).
