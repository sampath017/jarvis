# Android local storage

The desktop client and device sharing have been removed. Android usage totals,
recordings, recording names and archive choices remain on the phone. No sign-in
is required for these features.

Notes, reminders, places and chats live in `jarvis_mobile.db` using SQLite WAL.
The API has a SQLite working cache for AI requests and changes returned to the
phone. Cache generations invalidate sync cursors after a server reset. The phone
re-uploads its records and never treats an empty bootstrap as a deletion.

Only explicit deletion events remove local synchronized records. Existing local
files are retained; uninstalling the app or clearing app data removes them.
Google Drive/Calendar remain optional connected integrations. There is no Firebase,
Cloud Storage bucket, Chroma Cloud or desktop synchronization dependency.
