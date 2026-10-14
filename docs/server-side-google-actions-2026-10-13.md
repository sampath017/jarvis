> Historical release notes. The Android-only local storage migration supersedes the storage and deployment details below; see [current storage](android-local-storage.md).

# Unattended Google actions: deployed integration

The user wants explicitly scheduled actions to execute while the phone is
unreachable or the user is busy. Server OAuth configuration and the owner's
Google consent are complete. A real authenticated Cloud Tasks callback renewed
Google access and completed a read-only Drive search without the phone.
No Calendar event was created during verification.

## Why the previous implementation waited for the phone

Previously, `backend/src/cloud/calendar_tools.py` dispatched Calendar operations through
the command execution's device bridge. `CommandRunStore.calendar_action`
waits up to 180 seconds for the phone result. Google authorization is renewed
through Play services on Android; the backend had no offline Google grant.
Calendar writes also require a foreground approval through `CalendarExecutor`.
These are application design choices, not restrictions of Google Calendar API.

## Desired behavior

For “Tomorrow at 9, create a Calendar event called Lokesh meet from 4 to 5”:

1. Resolve the execution date, event date, start/end, destination calendar and
   account when saving the request. Ask only for genuinely missing details.
2. The user's explicit instruction authorizes that concrete scheduled action.
   Record its scope, including any guest invitations, with the schedule.
3. Persist the action and status in Firestore and enqueue durable Cloud Tasks
   work. Creating an action and enqueuing it need an outbox/reconciliation path
   so a task-creation failure does not lose the action.
4. At the execution time, an authenticated task handler refreshes server-held
   Google authorization and calls Calendar directly. No phone approval or
   device callback is required for the authorized action.
5. Save Google's confirmed outcome, action receipt and audit record. Queue a
   notification for later delivery. If authorization is revoked or expires,
   record “reconnection required” rather than claiming success.

Google API and cloud/network failures can delay completion; a due time is not
a guarantee of exact execution to the second.

## Required implementation

The following components are implemented. Activation steps appear below.

- A Google OAuth authorization-code flow requesting offline access, with a
  one-time user consent step. The backend exchanges the code for access and
  refresh tokens; copying a short-lived Android access token is insufficient.
- Private durable token storage, protected with encryption and IAM. Tokens
  never enter LLM prompts, chat sync or logs. Disconnect revokes/removes the
  relevant grant and disables dependent schedules.
- Account-bound authorization for every connector and schedule endpoint.
  The existing fixed `jarvis_local_user` dependency cannot safely be used as
  the sole authority for a server-held renewable Google grant. Use verified
  user identity or an explicitly provisioned, private personal capability.
- A backend Calendar executor with input validation, scoped authorization,
  ETag checks for edits and an operation ledger. Creates use deterministic
  Google event IDs and verify conflicting IDs before treating them as a
  prior success. Ambiguous write results are reconciled before retrying.
- A separate scheduled-action record, rather than interpreting notification
  reminders as arbitrary executable actions. Store the exact arguments,
  execution time, authorization scope, retry state and result.
- Natural-language tools to create, list, cancel and inspect scheduled actions.
  Do not run an unconstrained LLM again at the due time; execute the saved
  action. Scope any recurrence explicitly and allow cancellation.
- Frontend connection status, schedule management and failure/reconnection
  notices. Existing interactive phone execution can remain a fallback while
  server authorization is being introduced.

## What can be independent of the phone

Calendar and authorized Drive operations can use server-side Google APIs.
Already stored notes, reminders and indexed files can also be handled in the
cloud. Fresh GPS, sensors, Health Connect records, local-only attachments and
Android ringing require the phone or previously uploaded evidence. A trigger
such as “when I arrive home” still needs fresh phone observations; a scheduled
time-based action can execute without them.

## References

- [Google OAuth offline access](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Token storage and expiry practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)

The Google consent step is an account-owner action. It cannot be completed by
the assistant on the user's behalf. After authorization, supported schedules
should run without requiring the user to open Jarvis for each execution.

## Activation

1. Open [Google Auth Platform Clients](https://console.cloud.google.com/auth/clients?project=jarvis-agent-61947).
   Create a Web application client named Jarvis server with this authorized
   redirect URI:

   `https://jarvis-backend-pi6ef2rq5q-el.a.run.app/google-server/callback`

   JavaScript origins are unnecessary for this authorization-code flow.
   Download the JSON at creation and keep it outside the repository. It must
   contain the web client secret, not just an Android/Firebase configuration.
2. On the updated phone, open Settings → Cloud actions and copy the cloud setup
   identifier. This is a hash used to pair the private phone capability; it is
   not the private capability itself. The fixed local UID alone cannot select
   or authorize this cloud grant.
3. Run `backend/scripts/configure_server_google.py` with `--oauth-file`,
   `--owner-hash` and `--account`. It stores the OAuth client secret and a stable
   encryption key in Secret Manager, grants the backend identity access only
   to those secrets, and configures the allowed account and private connection.
   It also configures an authenticated five-minute Cloud Scheduler reconciliation
   job for pending queue delivery and result notifications. This setup was
   completed after the user approved the named credential destination and access.
4. In Settings → Cloud actions, connect Google and accept the requested offline
   Calendar and Drive access. The backend verifies the allowed email and scopes,
   encrypts the refresh token in its private connection record, and uses only
   access tokens in memory for Google requests. It never passes renewable tokens
   to the language model or normal chat synchronization.

External OAuth apps left in Testing have seven-day refresh tokens for these
scopes. Production publishing is needed for long-lived use; revocation and
expiry still require reconnection. See [Google token expiry rules](https://developers.google.com/identity/protocols/oauth2/).

## Current scope and limitations

Calendar list/read/create/update/delete can use the server. Drive search checks
current access and source versions before using indexed passages. Supported
files can be downloaded under a hard 20 MB bound and analyzed on the server;
large files require verified indexed evidence. Existing upload-cache files can
be promoted to My Drive without creating duplicates. Local-only attachments
must first be uploaded from the device. Forms use bounded form-structure and
response reads, with at most ten responses per analysis. Drawings are exported
as images and shortcuts are resolved with a bounded depth. Other unsupported
native Google formats remain explicitly unavailable.

Scheduled actions support exact Calendar operations and the supported Drive
search/analysis/save operations. There is no new recurring-schedule engine.
Event recurrence can be explicitly included in a Calendar event. Generic
notification reminders retain their existing behavior; the assistant should
not silently turn a notification request into an executable action.

Ambiguous external writes are not blindly replayed. Calendar create uses a
deterministic Google event ID and operation marker for reconciliation; edits
use ETags. A crashed scheduled worker can be marked failed with instructions
to check already completed changes. This implementation does not claim exactly
once delivery under every network failure.

## Validation and release

- 94 backend regressions passed, including 27 new cloud authorization/action
  cases; all Google calls in tests were mocked.
- 26 Flutter regressions passed; static analysis was clean.
- The release APK built and was installed with app data preserved.
  SHA-256: `c891f9cdf639530cea59434a86539f701c88487a680fe36026d90f9a3dc7951f`.
- Backend revision `jarvis-backend-00134-fov` received 100% traffic after candidate
  health, schema, private-access and configuration checks passed.
  The public health endpoint is healthy and retains the INR 50 AI allowance.
- Cloud Build `a92757ad-2f51-46ee-96e7-6f590fa3e442` succeeded.
- The first post-install process did not remain running. Relaunch recovered;
  the process and monitoring foreground service were then present. Inspected
  package-scoped logs showed no matching fatal/plugin/SQLite errors. No claim
  of uninterrupted runtime or a live Calendar write is made.

All changes are uncommitted. The cloud grant is connected and the read-only
task verification completed (schedule `86fdc1552ac1479a7964e1b51891da81668a160b99d1e5a75f362d41b7ee4006`).
This section records the Google integration release; subsequent power-toggle
deployment details are recorded in [runtime power](runtime-power-2026-10-13.md).
