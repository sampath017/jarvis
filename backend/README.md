# Jarvis Android processing API

FastAPI/LangGraph processes Android commands and context events. Run `uv sync` and
`uv run backend`. `JARVIS_STORAGE_MODE=mobile` is the default production mode.

App records exist only in request-scoped RAM workspaces and return as changes for
Android SQLite. Firebase, persistent server chat storage, cloud OAuth sessions,
background jobs, backups and sync endpoints are absent from the production API.
Tracing and user-content file logging are disabled in mobile mode.

The existing Chroma Cloud document index and embedding compute service remain:
configure the existing `CHROMA_HOST`, `CHROMA_API_KEY`, `CHROMA_TENANT`,
`CHROMA_DATABASE`, and `EMBEDDING_URL` values. Document chunks and vectors stay in
Chroma. File sources are processed temporarily; no bucket staging is required.

`JARVIS_STORAGE_MODE=legacy-local` exists for offline regression suites and local
repository testing. It is not the deployment storage architecture.

See [the storage guide](../docs/android-local-storage.md).
