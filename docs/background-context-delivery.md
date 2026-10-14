# Background context delivery and recovery

Departure reminders support satellite boundary, walking and home-network evidence
without a fixed neighborhood radius or a map editor. See
[departure boundaries](departure-boundaries.md) for setup and confirmation limits.

Jarvis collects Android activity transitions, qualified activity samples and bounded location evidence while monitoring is enabled. The native event queue is durable phone state. Upload jobs are wakeups for this queue; they are not the records themselves.

## Normal event flow

1. Accepted ENTER/EXIT events request a fresh bounded location fix. A durable location worker provides fallback attempts.
2. A coalesced upload worker selects ready observations in original chronological order. An unresolved location does not block later ready observations.
3. Fresh events use the same configured backend URL/user selection as foreground chat. The endpoint is persisted natively and survives process death/reboot.
4. The backend processes the event and returns request-scoped changes. Android commits the changes before acknowledging the event.
5. Saved reminder policies evaluate fresh eligible observations. A matching activity-delay policy becomes a normal local clock reminder; AlarmManager owns the later delivery.

Each request includes the SQL continuity state for the active reminders it carries. Android joins `record_dynamic_reminder_state` to active, undeleted reminders by ID and owner, rather than selecting an arbitrary recent set of states. This preserves an observed visit (`origin_seen`) across separate requests so a later departure can match. Completed, deleted, orphaned and other-owner states are excluded.

Activity samples are requested every 30 seconds and filtered for confidence/agreement. Location subscriptions request approximately 30 seconds while moving, 120 seconds in ordinary idle mode, or 30 seconds with dynamic monitoring. Distance/minimum-interval gates also apply. Periodic WorkManager checkpoints request 15-minute intervals; dwell follow-up requests 100 seconds. These are requested schedules, not guaranteed delivery deadlines.

## Bounded queue draining

`ContextUploadPolicy` selects up to four ready live events and 100 historical observations per plan. A worker processes at most four network events, 500 archived observations and approximately 45 seconds between operations. A network operation already underway retains its transport timeout.

One unique KEEP drain replaces per-event APPEND chains. A separate replaceable wake worker covers completion races, interrupted drains and bounded retries. Periodic checkpoints request the same drain. Retry delays grow from 5 seconds to a maximum of 60 seconds instead of leaving new observations behind hours of WorkManager backoff.

Queue scheduling version 3 retires old APPEND chains using WorkManager's API, cancelling each unfinished root once on a dedicated executor. Cancelling every named descendant repeats traversal of the same long chain and is intentionally avoided. This scheduling upgrade never clears event preferences or directly edits WorkManager's database; it is separate from the completed SQL record conversion.

## Historical observations

Events at least five minutes old are preserved locally as raw `context_memory` records with their original timestamp, location and evidence, plus idempotent event receipts. They do not replay old reminders, perform Places/LLM calls or mutate the present journey. Queue acknowledgement follows the successful local transaction.

Malformed timestamps and excessively future-dated observations are kept losslessly in `context_processing_errors`, without inventing an observation time. Other observations remain processable. Briefly future-dated observations defer until their time rather than bypassing the backend's age check.

The backend also has an early history-only path for stale events received from another client path. It preserves observations before graph/model/Places/reducer/automation work. This avoids treating historical replay as evidence of present activity.

Historical preservation cannot recreate an alert at its original time. A missed departure remains a missed occurrence, and future valid observations continue evaluating the saved active policy.

## SQLite boundaries

Android's `PRAGMA busy_timeout=10000` returns a row and must be consumed through `rawQuery`, not `execSQL`. Native initialization closes its handle if setup fails.

The backend imports domain rows and agent-state rows in one SQLite transaction. Named `state_*` tables hold agent continuity separately from the domain tables; both use parameterized SQL. Nested operations use savepoints. Real phone payloads contain both namespaces, so an empty synthetic payload alone cannot verify this contract.

Android reads named `domain_*` and `record_*` entity tables through the shared Dart/Kotlin `MobileSqlStorage` schema. The one-time phone conversion verified all 2,244 old rows against their converted SQL values and preserved active reminders and historical observation timestamps. The old generic tables, temporary migration archives and compatibility/conversion code were removed after verification. They are not part of queue draining or current requests. Context-history archival and timestamp-error quarantine remain current evidence records, separate from the deleted migration copies.

## Verification

- Pure Kotlin queue-policy regressions cover age boundaries, mixed backlogs, ready-event ordering, pending locations, malformed/future observations and retry limits.
- Dependency-free Android instrumentation runs real SQLite operations against isolated temporary databases. It covers opening/reopening, committed WAL data, missing storage, transactional history, quarantine and unchanged live state/budget/alerts.
- Flutter tests verify that background endpoint/user configuration follows the foreground selection.
- Backend tests cover atomic mixed SQL imports, request isolation, named entity queries and stale-history handling without graph or reminder execution. Conversion was separately verified on the existing phone database before the conversion code and temporary copies were retired.

Example device regression command after installing the debug app and its test APK:

```powershell
adb shell am instrument -w com.jarvis.jarvis_collector.test/com.jarvis.jarvis_collector.MobileRecordsOpenInstrumentation
```

Use `-e mode open` before the runner name to select the four database-open/protocol tests. Diagnostics and evidence stay under ignored `tests/coding_agent_artifacts/`; debug APK installation preserves phone records. See `android-development.md` for debug endpoint and production-traffic boundaries.
