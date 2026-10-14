> Historical release notes. The Android-only local storage migration supersedes the storage and deployment details below; see [current storage](android-local-storage.md).

# Jarvis development power switch

Settings → Jarvis power controls the whole Jarvis development runtime. Off is
persistent across app closure, package updates and phone restarts. Saved data,
Google account permissions and secrets are retained, so On can resume them.

## Off behavior

- Phone: stop recording/sensor streams and wakelocks, unregister activity and
  passive location, stop foreground monitoring, cancel workers and local alarms,
  disable FCM auto-initialization, ignore incoming push callbacks, close HTTP
  connections, and stop polling/sync/backup uploads. Native workers and receivers
  check the durable preference before doing anything. A powered-off app launch
  opens Settings and makes no cloud request.
- Backend: persist `runtime_control/jarvis.enabled=false` before cloud shutdown.
  An ASGI gate rejects application requests and background callbacks with 503.
  Active agent/model/tool entry points check the gate cooperatively. Reminder
  sweeps sleep locally while Off and do not poll Firestore. Incoming requests
  can still incur a small request/state-read cost; Jarvis itself stops issuing them.
- Cloud: pause the `jarvis-background` Cloud Tasks queue, pause the five-minute
  `jarvis-google-actions-reconcile` Scheduler job, and cancel active
  `jarvis-drive-indexer` executions. The embedding service has no remaining
  Jarvis caller. Backend and embedding services have minimum instances zero.

The private paired phone's `X-Calendar-Session` capability protects
`GET/PUT /runtime/power`; a fixed user ID cannot change project power. The
control route remains reachable while Off so On can wake Cloud Run. Power
changes use a durable transition lease. Partial cloud shutdown never reports
success, and a partially failed resume leaves the cost gate closed.

## On behavior

On makes a deliberate authenticated control request. Cloud Tasks/Scheduler
resume, interrupted staged indexing is queued for resumption, the backend gate
opens, and the phone restarts its saved monitoring/sync connections. Individual
usage/monitoring preferences and Google grants are preserved. Overdue schedules
and reminders may run after On; the switch explains that behavior.

An offline Off immediately stops the phone but cannot reach Google Cloud to
pause it. Settings says cloud shutdown is unconfirmed and offers Retry cloud
shutdown. No automatic background retry reconnects an Off phone. Reopening an
On phone checks cloud power once; an unreachable control plane keeps local work
off until an explicit retry.

Already accepted Google writes/model requests cannot be undone by closing a
connection. Their completed changes remain saved. Cloud Run shutdown/scaling
and job cancellation are asynchronous; the controller waits for cancelled
index executions to stop before confirming shutdown.

## Cost boundary

Scale-to-zero stops idle Cloud Run instance compute, not all project billing.
Firestore/GCS/Chroma stored data, container images, Secret Manager secrets,
retained Scheduler jobs and existing logs can still have storage/resource
charges. Control requests and outside clients (including a cloud console or a
caller using the public API) can produce usage. Off preserves resources rather
than deleting data or switching off billing. Build/deploy work also has usage.
Free quotas can cover some retained resources: Firestore includes 1 GiB of stored
data, and Scheduler includes three jobs per billing account. A paused Scheduler
job still counts toward that quota. These are allowances, not a guarantee that
the whole project has no bill. See [Firestore pricing](https://cloud.google.com/firestore/pricing)
and [Scheduler pricing](https://cloud.google.com/scheduler/pricing).

Reference: [Cloud Run billing](https://cloud.google.com/run/docs/configuring/billing-settings),
[Cloud Tasks pause](https://cloud.google.com/tasks/docs/reference/rest/v2/projects.locations.queues/pause),
[Cloud Scheduler pause](https://cloud.google.com/scheduler/docs/reference/rest/v1/projects.locations.jobs/pause).

## Verification

- 71 selected backend tests passed, covering private control authorization,
  request/task blocking, durable Off, partial stop/resume, command and paid-model
  gates, Google actions, budgets and existing background delivery.
- Ten focused power tests passed after final transition/idempotency checks were
  added, including actual cloud API pause/cancel orchestration with mocked transport.
- 117 Flutter tests passed, including no-network Off relaunch, local shutdown
  before cloud requests, offline shutdown status, gated HTTP and command sends.
- Static analysis reported no issues. The release APK built and was installed
  on the connected POCO phone with app data preserved.
  SHA-256: `a5790a26916e910b13615aeb07cbe077151db58b2020af7ce7cd813d8b67edad`.
- Cloud Build `be92f963-0872-47f7-9cf2-27b393d11167` succeeded. Backend revision
  `jarvis-backend-00137-mis` received 100% normal traffic. Its request-based CPU
  setting is enabled and no minimum instances are configured.
- The Drive indexer has the power guard and `JARVIS_POWER_CLOUD=1`. Its previous
  registry image had been removed; the updated indexer uses the current tested
  backend application runtime while preserving its command, resources and mounts.
- A real phone Off toggle persisted `enabled=false`, `cloud_ready=true`, paused
  the Tasks queue and Scheduler, and left zero active index executions. Monitoring
  and recording foreground services disappeared. The live sync endpoint returned
  503 with `power_off=true`; the control-plane health endpoint remained healthy.
- The phone was force-stopped and reopened while Off. Its persisted Off switch
  and confirmed shutdown message were observed after the user unlocked the phone.
  Cloud request logs during Off contained only the two deliberate verification
  calls (`/health` and rejected `/sync/pull`), with no app polling/sync observed.
- The actual phone On switch restored `enabled=true`, `cloud_ready=true`, queue
  `RUNNING` and Scheduler `ENABLED`. The app was left On after the complete test.
  Android monitoring resumed as foreground service notification 1002.
  Existing data and Google pairing were preserved. The device was not rebooted;
  boot/update receivers have the persistent gate but a physical reboot is untested.

All changes remain uncommitted.
