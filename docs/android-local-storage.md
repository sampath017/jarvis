# Android app storage and Chroma document retrieval

Android is the only client. SQLite with WAL owns chats, notes, reminders, saved
places, context history, usage accounting, and indexing progress. Ordinary
attachments stay in app-private files. Recordings first try Downloads/JarvisTelemetry,
then app external storage and app documents, so their visibility depends on the
selected path. The production API supplies computation rather than persistent
app-record storage. Android system backup and device transfer are disabled for
the application's private data; weekly Drive database backup is separate.

## Chroma is retained

Document chunks and embeddings remain in the existing Chroma Cloud collection
`jarvis-drive-eg2-768-v1`. Existing `CHROMA_HOST`, `CHROMA_API_KEY`, `CHROMA_TENANT`,
`CHROMA_DATABASE`, and `EMBEDDING_URL` settings are preserved. File readers split
documents; the embedding service produces vectors; Chroma stores and retrieves
relevant chunks. SQLite does not replace this vector store. Drive content retrieval
continues to check current access and source versions.

## Cloud Run processing

App records are available to Python tools only in request-scoped SQLite `:memory:`
workspaces. Commands request bounded, tool-specific reads from Android rather than
uploading the whole database. Sensor events carry active rules, nearby saved places,
and recent continuity state. Results return changes for the phone to commit.

Named SQL tables store each entity. Android uses `domain_*` tables for domain state
and `record_*` tables for agent continuity; Python uses matching entity repositories
and `state_*` continuity tables in its temporary workspace. The request contract
uses `agent.domain`, `agent.records` and explicit deleted keys. Scalar fields have
SQL columns; nested values use JSON columns.

Android commits changes transactionally, deduplicates operation receipts and usage,
and preserves newer phone edits if a command used an older record version. Cloud
Run retains active command coordination and a short completed-response delivery
window in RAM. A missing request after a restart is not automatically re-executed.
Keep Jarvis open while a command needs phone reads or Google actions.

No server SQLite file, persistent chat cache, user-content log, tracing service,
Google token store, bucket upload staging, cloud backup, or background task queue
is used by the mobile API. File indexing uploads bounded source bytes for temporary
processing and writes only the document index to Chroma. Index progress and scan
resumption are phone-owned. Existing complete Chroma chunks are reused by digest.

## Offline behavior and existing data

Local notes, chats, recordings, usage reports, and time reminders work offline.
The Overview preloads 30 days of full app-usage summaries from private SQLite
(`jarvis_usage_history.db`) when Jarvis starts. Date navigation reads this memory
cache without querying Android activity events. The Overview tab is mounted at
startup, and its horizontal pager lays out adjacent dates in advance, retains
visited pages and their scroll positions, and slides between dates on arrow taps
or swipes. Background work collects recent
days every 15 minutes while Jarvis is enabled; the visible Overview refreshes
today at most once per minute. Completed days are reused, and yesterday's partial
snapshot is finalized after midnight IST. Existing daily reports are imported.
Initial collection can only recover the recent raw events Android still retains;
saved summaries remain available for the full 30-day overview window. Overview
shows the five most-used apps, with the complete total and breakdown retained
for chat.

Android AlarmManager schedules time alerts; context computation and AI need a
network connection. Google Calendar and explicit Drive saves use phone authorization.
Ordinary attachments are not automatically uploaded to Drive. Local chat archives
are organization on the phone, not backups.

On 28 October 2026, the existing phone database was converted and all 2,244 old
rows were checked against their SQL values. Existing reminders and their status
were preserved. After that verification, the generic old tables, temporary
migration archives and compatibility readers/conversion code were removed. The
final application reads only the converted SQL entities; it does not retain an
alternate document-style store or a recurring old-record import path. Context
history and timestamp-error quarantine are ordinary current records, separate
from the removed migration copies.

An in-place APK update retains the converted phone data. Uninstalling or clearing
app data removes it. Historical remote records and old Drive files are separate
resources; this local conversion does not import them into the phone database.

Chroma, model inference, Maps, and Cloud Run retain their existing service costs;
there is no new managed database for app records. Dated engineering documents
outside this guide describe older releases.

## Weekly Drive database backup

The phone now offers a weekly database backup to `Jarvis/jarvis_db_backup.db`,
using its connected Google Drive account. It updates one managed file and removes
older revisions after verifying the replacement. See [weekly backup](weekly-database-backup.md)
for timing, scope, and controls. This is independent of local chat archiving.
