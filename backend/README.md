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
The query reads up to 5,000 observations and returns a grouped timeline,
missing periods, and an explicit truncation flag when a smaller query is needed.
`GET /context-memory` returns the latest 50 observations; adding
`?lookback_minutes=2880` returns a time-window recap. Nearby candidates are not confirmed
visits, stationary activity is not proof of sitting, and an inferred shop visit
is not proof of buying anything.

With context awareness enabled, Google Play Services wakes the phone for
walking, still, cycling, running, and vehicle transitions. A short delayed job
checks dwell after still or walking begins. The phone also accepts passive
location fixes produced by other apps or Android, recording a checkpoint after
at least 100 metres of movement. It requests one bounded location fix for a
fresh activity transition when the cached location is too old. Background
place history requires the Android "Allow all the time" location permission.
Native Android code durably queues these events before an upload worker sends
them to Cloud Run; retries preserve event IDs and timestamps. A periodic worker
recovers missed uploads and fetches pending reminder notifications. The Flutter
app polls only while visible. A foreground service is used only for an explicit
short IMU recording, with no long CPU wake lock.

Android may defer background work, and passive location fixes may be absent.
This is a sampled timeline, not a complete GPS trace. Delayed events remain
history; events older than five minutes do not generate immediate alerts.

One-shot reminder completion and its notification outbox entry are committed in
one Firestore transaction. Polling reads those notifications across Cloud Run
instances and records delivery acknowledgement without recreating alerts.
Historical observations inform chat interpretation; current alerts still require
fresh matching evidence. History cannot reconstruct movements that were never recorded.
