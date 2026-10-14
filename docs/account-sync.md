# Android records and account boundaries

Android owns notes, reminders, places, chats, usage history and recording
preferences. `jarvis_mobile.db` uses SQLite WAL. Local notes, chat history,
recordings and scheduled time reminders work without Google sign-in.

The production API receives an explicit working set, computes in temporary
in-memory SQLite, and returns changes. Android commits those changes locally with
operation receipts and version checks. This is a computation protocol, not a
second durable replica or a cross-device synchronization service. A missing API
request after restart must not be automatically repeated as a new operation.

Google Drive and Calendar are optional, phone-authorized integrations. Chroma
retains the document index and embeddings; it is separate from application-record
storage. A private phone capability scopes file/index requests and is not a
multi-user login system.

In-place APK updates retain phone data. Clearing app data or uninstalling removes
app-owned records/files; public recording files can remain. The optional weekly
Drive snapshot covers only the main database and currently has no in-app restore
workflow. It is independent of local chat archiving.

See [storage ownership](android-local-storage.md), [weekly backup](weekly-database-backup.md),
and [Google Calendar](google-calendar.md).
