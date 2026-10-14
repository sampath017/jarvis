> Historical release notes. The Android-only local storage migration supersedes the storage and deployment details below; see [current storage](android-local-storage.md).

# Automatic chat archives — October 14, 2026

Automatic archiving is enabled by default. Jarvis checks in the cloud every day at **3:00 AM local time** and archives conversations inactive for **30 days**. Manual archiving remains available in **Settings → Chat archives**, alongside the automatic archive switch.

New backups are saved in **My Drive/Jarvis Chat Archives** with names like `jarvis-chat-<conversation>-<timestamp>.json.gz`. Existing archives in My Drive remain readable at their original file IDs; they were not moved or deleted.

## How inactivity is determined

The server uses the most recent known opening/use timestamp, session update and message activity. An ongoing command protects its conversation. This is a deterministic rule, so checking inactivity does not consume model tokens.

Opening, selecting or resuming a visible conversation sends a non-blocking usage update when the app is online. Updates are coalesced to at most once per thread per hour. Sending/editing a cloud message updates its parent activity timestamp in the same transaction. Restoring an archive also renews activity. Notification refreshes and local database refreshes do not make unused chats appear recently opened.

Offline openings cannot update the cloud until connectivity is available; the app records the selected chat when its health check comes online. Phone history is retained even if an older cloud conversation is archived. Future-dated, malformed or timezone-ambiguous activity timestamps do not qualify a chat for automatic retirement.

## Backup and deletion safeguards

1. Verify the paired cloud Google connection and a private, user-owned archive folder.
2. Merge any existing verified Drive archive with the conversation's current Firestore messages. Preserve older message IDs and metadata when a previously archived chat is continued.
3. Allocate a Drive file ID and retain a small upload receipt so a retry can reuse the same immutable backup.
4. Upload compressed data, check file ownership/privacy, download the uploaded bytes and compare their SHA-256 hash.
5. Recheck recent activity, automatic policy, power state and command lease inside each bounded retirement transaction. Verify every message against the backup before deleting its cloud copy.
6. Keep the conversation manifest in Firestore and retain the full local phone history. Restore from Drive when needed.

Turning automatic archiving off does not disable manual backups. Jarvis's power switch pauses the daily scheduler together with existing background tasks. Disconnected Google access, corrupt archives, changed conversations and failed uploads preserve Firestore message copies.

The daily worker migrates up to 200 legacy session metadata rows per pass and examines up to 20 archive candidates. A cursor rotates past failed/deferred backups so they do not indefinitely block other conversations. Leases, a daily completion checkpoint and a time limit prevent overlapping/repeated daily work. This release keeps previous immutable archive generations; it does not delete older Drive backups automatically.

## Cost behavior

The new Firestore index covers `uid`, `archive_pending`, `archive_activity_at` and document ID. Daily checks fetch eligible session summaries first; message bodies are read only for old candidates with cloud data still pending archival. Fully archived chats leave that candidate query until new cloud messages arrive.

Usage tracking normally writes no more than once per thread per hour of observed activity. A changed cloud message adds one parent activity-marker write to the existing three-write sync transaction. This extra coordination prevents the archive worker from racing a new message. Legacy metadata migration is a bounded initial cost; it does not fetch every historical message.

## Release and verification

- Backend revision **`jarvis-backend-00143-quj`**, 100% default traffic, `asia-south1`.
- Image `auto-archive-20261014-135631`, digest `sha256:b811943aea90868182f1214652ef5043c024ad89243239cb1cf7d8d111c3f5c2`.
- Successful Cloud Build `b1e41565-9a3b-4cf6-811f-1f62855c868c`.
- Backend/indexer share the new image; their resource settings, job command, secrets and existing scheduling are retained.
- Scheduler **`jarvis-chat-archive-daily`**, `0 3 * * *`, timezone `Asia/Kolkata`, authenticated with the existing background callback identity.
- Composite Firestore index `CICAgOjXh4EK`, verified **READY**.
- Initial authenticated daily run succeeded: **0 candidates, 0 archives, 0 errors**. No existing conversations had reached the inactivity threshold. The archive folder was created and legacy metadata migration completed.
- **100 distinct backend tests passed** across the focused archive, API, sync, query, Google-access, command and power suites. **133 tests passed in the full Flutter suite**; static analysis was clean.
- Live Firestore SDK smoke test verified the index, metadata migration, guarded retirement, manifest, daily lease/checkpoint and use tracking. Only isolated generated test conversations were used, and all test records were removed.
- The release APK was installed successfully on the connected POCO phone at **19:29:51** local time using `adb install -r`; the original first-install time and saved app data were retained.
- APK SHA-256: `8a2f84dea5682fc9125349096c70a0dee56e6d3a051929d1dfa0b90eabf6a975`.
- The phone was locked during the final UI inspection; installation and process checks succeeded, and no post-install process crash/SQLite failure was observed. Device UI validation is limited to those checks and the passing Flutter suite.

Deployment metadata and verification results are saved locally in `tests/coding_agent_artifacts/deployment/snapshots/backend/auto-archive-release/` (Git-ignored). The APK is at `mobile/build/app/outputs/flutter-apk/app-release.apk`. All changes remain unstaged and uncommitted, following the project rule.
