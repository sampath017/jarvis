# Google Calendar in Jarvis

Open **Settings → Google Calendar → Connect Google account**, choose your account,
and accept Google's Calendar consent. Choose the default calendar. Google is the
only provider supported. Keep Jarvis open while running calendar commands.

Ask to list events, read an event, create a meeting, reschedule it, edit its title,
location, description, guests or recurrence, or delete it. Jarvis searches before
targeting an existing event and asks which one when the request is ambiguous.
Calendar account settings, sharing ACLs and deleting entire calendars are outside
the allowed operations.

Every calendar write shows the exact event, destination calendar, before/after
details, guests and notification impact. Decline or dismiss to leave it unchanged.
An approval covers one proposal. Entire recurring series require explicit scope
and a series warning; otherwise use an occurrence. All-day end dates are exclusive.
Google notifications use `sendUpdates=all`, disclosed in the approval preview.
Other saved-data writes through the current Jarvis chat client also require an
approval preview; reads remain automatic.

Google access tokens remain in Android process memory. Google Play services renews
authorization for the selected account. Tokens are not sent to Jarvis's backend,
LLM, logs or Firestore. Relevant calendar event content is sent to the existing
Jarvis backend/LLM to answer requests and may appear in normal chat/history.
The existing backend uses a single local user rather than account-based Firebase
authentication. The new command/action endpoints are protected by a device secret;
this does not upgrade the existing chat/sync endpoints to per-user authentication.
Do not treat this personal deployment as a multi-user service.

Calendar event changes use Google's event ETag with `If-Match`. If another app
changed the event, Jarvis stops and requires a new proposal. The device records an
operation before dispatch; after a lost response or crash it refuses to repeat
an uncertain write. Check Google Calendar before issuing a new request in that
case. Approval expires if its request stops or the device connection changes.

Disconnect removes the local connection and device session secret. Google's
account settings can additionally revoke Jarvis's OAuth grant.

## Google project setup

Project: `jarvis-agent-61947`. API: `calendar-json.googleapis.com`.
Android package: `com.jarvis.jarvis_collector`.
The current sideloaded release uses the existing debug signing certificate:
`F3:66:EB:41:B3:22:80:D3:79:3E:BE:DD:4C:1D:BF:AA:1D:F4:EA:7F`.
Register the corresponding Android OAuth client for every signing certificate used.
The Firebase Android app registration and current SHA-1 were restored/registered
through `backend/scripts/configure_calendar_android.py`; the local
`google-services.json` was refreshed from Firebase.

Required scopes:

- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/calendar.calendarlist.readonly`

Configure Google Auth Platform branding/audience and, when in Testing, add the
Google account as a test user. Google's consent/audience settings can require an
account-owner step. The app never completes Google consent on the user's behalf.

## Validation

Flutter calendar tests use mocked Google HTTP responses. They exercise declined
approvals, all write types, cancellation during approval, background refusal,
crash receipts, changed proposals, pagination, invalid payloads and ETag conflicts.
Backend tests exercise absent device authorization, private request capabilities,
proposal privacy and approvals for existing saved-data tools. No test changes a
real Google Calendar event.
