# Weekly database backup

Android schedules a backup for Sunday around 03:00 in Asia/Kolkata, with a first
backup after Google Drive is connected. WorkManager waits for network access and
adequate battery; Android may delay background execution. Powering Jarvis off
pauses backups. Turning it on restores the weekly schedule.

The file is `Jarvis/jarvis_db_backup.db` in the connected user's private My Drive
folder. It contains a consistent snapshot of `jarvis_mobile.db`, including
committed WAL changes. It does not contain separate audio/attachment files,
Google authorization credentials, or native sensor/preferences databases.

The worker verifies the SQLite snapshot and compares the uploaded size and MD5
before removing older revisions of this managed backup. Later backups update
the same Drive file. It does not delete other files or folders. Interrupted
uploads retry without treating a queued job as a completed backup.

Settings provides an enable switch, last successful backup, error status, and
**Back up now**. If permissions expire, reconnect Google Drive. The worker never
opens account or consent dialogs in the background.

Implementation references: [SQLite VACUUM INTO](https://www.sqlite.org/lang_vacuum.html)
and [Google Drive revision management](https://developers.google.com/workspace/drive/api/guides/manage-revisions).
