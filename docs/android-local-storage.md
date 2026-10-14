# Android app storage and Chroma document retrieval

Android is the only client. SQLite with WAL owns chats, notes, reminders, saved
places, context history, usage accounting, and indexing progress. Recordings and
ordinary attachments stay in private phone files. There is no Firebase, Firestore,
FCM, application backup, export flow, or desktop client. Android system backup and
device transfer are disabled for the application's private data.

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
Android AlarmManager schedules time alerts; context computation and AI need a
network connection. Google Calendar and explicit Drive saves use phone authorization.
Ordinary attachments are not automatically uploaded to Drive. Local chat archives
are organization on the phone, not backups.

An in-place APK update retains existing phone data. Uninstalling or clearing app
data removes it. Cloud-only historical records are not automatically migrated.
Existing Firebase data, old Drive archives, and buckets are not erased by source
changes. Retired schedulers and task queues are stopped at deployment cutover.

Chroma, model inference, Maps, and Cloud Run retain their existing service costs;
there is no new managed database for app records. Dated engineering documents
outside this guide describe older releases.
