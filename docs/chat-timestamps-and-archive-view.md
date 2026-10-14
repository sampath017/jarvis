# Chat timestamps and local Archived view

Android persists full conversations in SQLite. New messages carry absolute UTC
instants; display labels use Asia/Kolkata. Ordering must preserve the question
before its answer even when timestamps or IDs originated in older formats.
`chat_message_time.py`, Dart chat models and timestamp regressions cover these
ordering/normalization rules.

The history UI exposes Recents and Archived. Current archiving retains the
conversation locally through `LocalChatArchiveService` and the SQLite archive
reference table. Opening or continuing a conversation does not require a Drive
chat restore. `needsRestore()` is false and `restoreHistory()` is currently a
no-op. Local archive organization is not a separate backup or cloud retirement
workflow.

The whole selected thread is loaded for a model command independently of UI page
size; see [conversation history](chat-memory-and-budget-2026-10-12.md).
The optional [weekly database backup](weekly-database-backup.md) snapshots the
main SQLite database as a separate feature. No in-app snapshot restore workflow
is currently provided.
