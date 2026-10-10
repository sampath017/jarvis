# Jarvis Backend API

Jarvis Context-Aware Mobile Agent — Local & Cloud Run API.

## Usage

```powershell
uv run backend
```

## Context and session memory

Firestore stores user-scoped `mobility_sessions`, `semantic_contexts`, and
`context_memory` under `users/{uid}`. Memory records retain the source event ID,
timestamp, observed activity, GPS when available, nearby place candidates,
session association, and inferred parking/dwell/shop contexts. Retried events
reuse the same memory document; older observations do not reactivate departed
semantic contexts. Repeated stops and shop visits have separate context IDs.

The assistant receives the latest 20 observations as a preview and calls
`recall_context_history(lookback_minutes=10)` or `lookback_minutes=2880` for
ten-minute or two-day recaps. Explicit `start_at` / `end_at` parameters accept
ISO timestamps with timezone offsets, with a maximum window of 31 days.
The query splits windows that reach 5,000 observations, with a bounded query
budget. Session totals use the retrieved observations; the timeline preview has
its own truncation flag. Incomplete source history cannot produce a reliable total.
`GET /context-memory` returns the latest 50 observations; adding
`?lookback_minutes=2880` returns a time-window recap. Nearby candidates are not confirmed
visits, stationary activity is not proof of sitting, and an inferred shop visit
is not proof of buying anything.

With context awareness enabled, Google Play Services wakes the phone for
walking, still, cycling, running, and vehicle transitions. A short delayed job
checks dwell after still or walking begins. The phone requests adaptive location
updates and also accepts fixes produced by other apps or Android. It records
checkpoints with time and distance limits and requests one bounded fix for a
fresh activity transition when the cached location is too old. Background
place history requires the Android "Allow all the time" location permission.
Native Android code durably queues these events before an upload worker sends
them to Cloud Run; retries preserve event IDs and timestamps. A periodic worker
recovers missed uploads and fetches pending reminder notifications. The Flutter
app polls only while visible. A separate low-power foreground monitoring service
keeps activity recognition registered while context awareness is enabled. It
requests fresh classifications independently of Flutter or an explicit short
IMU recording. No long CPU wake lock is held.

Native high-priority FCM context requests can wake the phone and return a fresh
location without opening Flutter. Requests are deduplicated, expire after two
minutes and have a durable receipt. Activity classifications require two fresh
agreeing Android samples with at least 80% confidence; cached state and orphan
exit events cannot create activity spans. User corrections remain explicitly
user-reported and do not erase gaps in sensor coverage.

Logical sessions preserve matching starts and exits through uncertain samples
and diagnostic checks. Generic ON_FOOT samples are compatible with an existing
walking/running session but cannot establish one alone. Coverage gaps remain
inside the session and are excluded from classification-supported duration totals.
Open intervals stop accumulating at the last positive observation. Late uploads
rebuild the same history in event-time order. These rules apply to future walking,
running, cycling and vehicle records as well as historical queries.

Android may defer background work, and passive location fixes may be absent.
This is a sampled timeline, not a complete GPS trace. Delayed events remain
history; events older than five minutes do not generate immediate alerts.

One-shot reminder completion and its notification outbox entry are committed in
one Firestore transaction. Polling reads those notifications across Cloud Run
instances and records delivery acknowledgement without recreating alerts.
Historical observations inform chat interpretation; current alerts still require
fresh matching evidence. History cannot reconstruct movements that were never recorded.

One-shot activity reminders can specify `activity_delay_seconds` (1–86,400).
A fresh matching ENTER starts a Firestore-backed countdown, delivered by an
authenticated Cloud Task even without subsequent phone events. Duplicate starts
retain the original deadline; deleted, paused or changed policies invalidate old
tasks. This is elapsed time after a detected start, not proof of continuous exercise.

For large Drive imports, use the [local bulk indexing workflow](../embedding/README.md)
and reserve Cloud Run inference for queries and small incremental updates.
