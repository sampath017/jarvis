# Archived chat UI and Jarvis Drive organization

Update, October 15: chat history now uses a simple **Recents** title list, sorted by latest activity, with no day headings or message-count/time subtitles. **Archived** is visibly available beside **Recents** and retains each archived chat's status. Message timelines also flow continuously without day dividers. Archive-management settings retain their dates. This replaces the date grouping described in the original release below.

Long-press a conversation to open Rename, Archive and Delete; per-chat overflow dots are removed. Archive is available directly from Recents and uses the same confirmation and verified Drive backup as Settings. It restores any older archive and loads the entire saved conversation before uploading, then moves the verified conversation into Archived. Archiving is blocked while that chat is receiving a response, duplicate archive requests are blocked, and sending into the conversation is disabled until the archive completes. Failures keep the conversation available and show an error.

Archived conversations now have a separate **Archived** tab in chat history, an amber background/icon and an explicit **Archived · saved to Drive** badge. Active conversations with an older archive show **Includes archived history**. A new message returns a fully archived conversation to the active list while retaining its restore reference.

Both history lists and message timelines display prominent date dividers with weekday, day, month and year. Today/Yesterday are accompanied by the full date. Local midnight boundaries and equal-timestamp ordering remain consistent with the existing phone display logic; no timezone suffix is added.

SQLite stores archive status alongside the existing archive reference. Its additive migration preserves previous references and conversation bodies. Archive state is updated by verified local backups, incoming server manifests and new/edited messages. Conversation-list loading remains summary-only, and older bodies retain cursor pagination. Summary rows now show message counts and last-message time rather than incorrectly describing unloaded conversations as empty.

The Drive layout is:

```
My Drive/
  Jarvis/
    Chat Archives/
    Upload Cache/
    Saved Files/
```

Existing Jarvis archive/cache folders are moved and renamed with their IDs preserved. App-marked Jarvis files previously saved in My Drive are placed in the appropriate child folder. New phone attachment uploads and explicit saves use these folders, as do server-side file saves and automatic/manual archives. The organizer operates only on user-owned private folders/files carrying Jarvis markers; original external documents selected for reading retain their user-chosen location. Old archive file IDs and download/restore references remain valid.

Backend revision **`jarvis-backend-00146-moq`** serves 100% default traffic. The shared backend/indexer image is `ui-drive-20261014-173846`, digest `sha256:b31b7c3281ba0a86552b0468e5a789ca04bd804e76c4db99b65b02a25eed9938`. Its successful Cloud Build was `fb585e8e-a365-46e5-aa14-cfc1d4fb3187`.

The authenticated organization task returned HTTP 200 on October 14. All four distinct root/child folder references were verified in the paired connection. The root folder is [Jarvis](https://drive.google.com/drive/folders/104RxAZwelE-OJ4EMVCGD1Mu3QWN4Y08k).

Validation: 136 tests passed in the full Flutter suite; the affected Drive/UI tests passed again after resolving the actual My Drive root ID. Static analysis was clean. The focused backend archive/organization/API/Google/power suite passed 77 tests. Regressions cover folder-ID preservation, original-document exclusion, private-folder enforcement, same-file promotion without duplication, canonical root aliases, archived-to-active transitions, and visible date/status controls on a 320-pixel screen.

The APK was installed in place on the connected phone, preserving app data. Final folder-path wording was rebuilt and installed as well. The phone was locked during the device screenshot check, so layout evidence comes from the Flutter widget tests rather than an unlocked device screenshot. Release metadata is saved locally in `tests/coding_agent_artifacts/deployment/snapshots/backend/ui-drive-release/` (Git-ignored); sources remain unstaged and uncommitted.
