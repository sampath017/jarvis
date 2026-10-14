# Google Calendar in Jarvis

Connect Google in Settings, choose the account/default calendar, and accept
Google's Calendar consent. Keep Jarvis open while a conversational command needs
phone execution. Supported operations list/read events and create, update or
delete a selected event; ambiguous targets require clarification. Entire-calendar
deletion and sharing ACL changes are outside the tool set.

Every Calendar write shows destination calendar, before/after event details,
guests, changed fields and recurrence scope. Approval covers that proposal only.
Writes can notify attendees using `sendUpdates=all`. Read operations do not need a
write approval. Routine local note/reminder actions have their own action policy;
Calendar approval rules do not imply every local write opens a dialog.

Google Play services authorizes the chosen account and renews access tokens in
Android memory. Tokens are not sent to the language model. Relevant event content
returns through the private command action channel for answering and can appear
in local chat history. The personal backend's fixed local UID is not a multi-user
login mechanism; request/action capabilities enforce the device handoff boundary.

Calendar edits/deletes require the existing event ETag (`If-Match`). A changed
account, expired request or backgrounded app stops execution. Android saves a
fingerprinted operation receipt before sending a mutation; an uncertain result
is not automatically repeated. Check Google Calendar before requesting a new
write after an interrupted operation. Creates use deterministic event IDs.

Disconnect removes the local connection; Google account settings can separately
revoke its grant. Android OAuth configuration must match the app package
`com.jarvis.jarvis_collector` and the signing certificate actually used. Enable the
Google Calendar API and configure consent/audience in Google Auth Platform.
Required scopes are:

- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/calendar.calendarlist.readonly`

No cloud-held renewable Google grant or scheduled server Google action is needed
for this current interactive phone flow. Weekly database backup uses the separate
Drive connection; see [backup](weekly-database-backup.md).

Tests use mocked Google responses for approvals, cancellation, receipts, changed
proposals, pagination, invalid inputs and ETag conflicts. They do not establish
that a live Calendar write succeeded. Main sources are
`GoogleAccountAuthorization.kt`, `google_calendar_service.dart`,
`calendar_executor.dart` and `tests/android/ui/calendar_executor_test.dart`.
