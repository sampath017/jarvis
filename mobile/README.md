# Jarvis Android

Run `flutter pub get`, then `flutter run -d <android-device-id>`.

Android SQLite with WAL owns chats, notes, reminders, places, context history and
usage records. Recordings and ordinary attachments stay in private phone files.
Android AlarmManager delivers time reminders without an open app or cloud request.
Backup, export, desktop sharing and Firebase are removed.

The API requests only bounded records needed by a tool and returns changes for
Android to commit. Google Calendar and explicit Drive saves use native phone
authorization. Cloud Run provides AI/context processing; the existing Chroma
Cloud settings and collection continue to store document chunks and embeddings.
Only indexing progress receipts are stored in SQLite, not a replacement vector index.

In-place APK updates preserve local data. Clearing app data or uninstalling removes
it; automatic system backup and device transfer are disabled.
