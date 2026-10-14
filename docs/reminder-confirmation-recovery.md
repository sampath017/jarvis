> Historical release notes. The Android-only local storage migration supersedes the storage and deployment details below; see [current storage](android-local-storage.md).

# Reminder confirmation and retry recovery

The second latest Jarvis chat, “Cloud actions,” requested “Call me in next 10 sec.”
The assistant asked for confirmation and then hit the repeated-step breaker on
“Confirm.” Both durable requests contained 24 prior messages. The original tool
arguments/results were not retained in cloud logs, so the precise rejected field
cannot be established from the historical trace.

The code had two relevant weaknesses: reminder input validation used the label
`CONFIRMATION_REQUIRED`, and unchanged failed writes could cycle through the
agent until the generic loop breaker stopped the request.

The repair makes these boundaries explicit:

- Reminder trigger and place validation failures return `status=invalid_arguments`, a stable error code,
  the affected field, `saved=false`, and `requires_approval=false`. A missing time
  requires a time or a correction from existing context, rather than “yes.”
- The obsolete `confirmed` argument is hidden from the model's tool schema.
  Older direct callers remain compatible; changing that flag cannot change the
  operation's idempotency key or authorize anything.
- Complete, unambiguous relative self-call requests ground the delay and
  `in_app_call` delivery in the user's actual message. This narrow normalization
  rejects negation, calls to someone else, mixed requests and extra conditions.
  General reminders still use the conversational agent.
- Corrected arguments may execute. Repeating the same failed reminder arguments
  returns the specific failure without another model call. Previously completed
  actions retain their IDs, and a failed result cannot add a changed-record ID.
- Tool logs distinguish failures from success and include run ID, tool name,
  error code, argument field names, and bounded scheduling fields. Titles, note
  bodies, coordinates and file identifiers are excluded from the new cloud
  outcome diagnostics.

`tests/backend/test_reminder_tool_recovery.py` exercises the real graph and SQLite
with scripted provider responses. The exact-request, corrected-argument and
failed-retry scenarios are also in `tests/harness/agent_cases.json`, repeated three
times by the agent suite. The graph regression verifies that 24 previous messages
still reach the model in order.

The release overlays five reviewed source files on the serving immutable image.
It requires passing backend, repeated-agent and final schema checks, and runs
offline smoke checks inside the built image. Deployment first creates a candidate
with no traffic, checks health and routes, and promotes only if serving traffic
has not changed concurrently. Failed post-promotion health checks restore the
previous revision. Release hashes, verification and rollback revision are saved
under `tests/coding_agent_artifacts/deployment/snapshots/backend/reminder-recovery-release/`.

The optional real-provider probe was not run: automatic approval review rejected
exporting the request to an external model provider with potential charges.
Offline/scripted workflow checks do not measure live model accuracy or verify
that the phone physically rings.

Release verification: `jarvis-backend-00157-xib` is healthy and serves 100% of
backend traffic. Cloud Build `2753d1e2-fb1a-4480-ab9a-2035adebbfc2` succeeded with
the mandatory image smoke checks. Validation passed 482 backend tests, 159
scripted agent checks over three repetitions, and 17 final focused checks.
The previous serving revision is `jarvis-backend-00154-paw`.

## In-place departure policies

The later milk-reminder conversation exposed a separate limitation: the tool
required a shop category for a journey. It deleted the existing record while
trying to rebuild that policy. `journey_origin="Gym"` now supports a departure
without any destination, nearby shop or movement condition. `update_reminder`
replaces those conditions on the same record, preserves its ID, and keeps
`in_app_call` delivery. Routine updates do not use the deletion approval path.

The prompt explicitly requires updates for existing policies. The execution
node also blocks a model-proposed deletion during a recognized policy edit,
returning `edit_in_place` before dispatching an approval. Explicitly requested
deletions still retain their human approval requirement. Regression tests
deliberately propose the wrong delete first and verify recovery to an update,
with the original ID intact and no approval dispatch.

Departure evaluation requires a fresh accurate inside observation followed by
an outside observation beyond the exit hysteresis boundary. It rejects stale,
inaccurate, duplicate and out-of-order samples; a first observation outside does
not prove a departure. Existing notification/outbox logic provides one-shot
delivery. Offline checks verify call delivery metadata, not physical ringing.

The desktop-dashboard release also adds owner-capability phone pairing,
device-bound usage snapshots and private desktop commands. Its packaged smoke
checks include the departure, in-place edit and private-route boundaries. The
release manifest is under `deployment/snapshots/backend/desktop-dashboard-release/`
inside the ignored coding-agent artifacts directory.

Verified release: `jarvis-backend-00160-gif`, healthy, 100% traffic. Cloud Build
`6723abbe-753a-4228-b639-00fc3b13fd16` passed its offline packaged checks.
Validation passed 499 backend tests, 154 mobile UI/service tests and 159 repeated
scripted agent checks. The Windows self-contained package passed SQLite and WPF
smoke checks, with all six main views rendered using synthetic data.

The original milk reminder `24229698-7813-4954-bbb4-1da826a7dccc` was restored
from the erroneous Trash operation and updated on that same ID: ACTIVE,
departure from the saved Gym, `in_app_call`, no shop/destination or movement
condition. Readback verified the saved policy. No replacement record or deletion
was performed. Phone ringing and live-provider interpretation were not tested.
