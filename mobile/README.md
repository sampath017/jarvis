# Jarvis Android

Run `flutter pub get`, then `flutter run -d <android-device-id>`.

Android SQLite with WAL owns chats, notes, reminders, places, context history and
usage records. Ordinary attachments stay in app-private phone files. Recording
storage first tries Downloads/JarvisTelemetry, then app external storage and app
documents; its selected path determines file visibility.
Android AlarmManager delivers time reminders without an open app or cloud request.
The phone can back up its main SQLite database weekly to a private Google Drive
file. See [backup scope and controls](../docs/weekly-database-backup.md).

The API requests only bounded records needed by a tool and returns changes for
Android to commit. Google Calendar and explicit Drive saves use native phone
authorization. Cloud Run provides AI/context processing; the existing Chroma
Cloud settings and collection continue to store document chunks and embeddings.
Only indexing progress receipts are stored in SQLite, not a replacement vector index.

`MobileSqlStorage` shares fixed `domain_*` and `record_*` entity schemas between
Dart and Kotlin. Native workers and Flutter read the same SQL records; request
changes use the `agent.records` row contract and explicit deleted keys.

The phone conversion verified all 2,244 existing rows and preserved reminder
status before the old generic tables and temporary migration copies were removed.
The final application contains no old document-style reader or conversion path.

In-place APK updates preserve the converted local data. Clearing app data or uninstalling removes
app-owned data; public recording files can remain. Automatic system backup and
device transfer are disabled. The weekly database backup is a separate feature.
