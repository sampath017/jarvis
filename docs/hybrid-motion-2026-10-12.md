# Hybrid motion monitoring

The eight missing-location activity samples investigated on 12 October were already 5–82 minutes old when received by the phone. All eight mapped to UNKNOWN. This establishes a phone-side timing problem, but does not distinguish Google Play services buffering from Android/vendor scheduling, or prove that genuine activity transitions were delayed.

## Implemented behavior

- Google's activity transitions and sampling remain the source for established activity automation. New native motion monitoring runs independently inside the existing monitoring foreground service. Its candidates go into a separate diagnostic store, never into journeys, activity duration totals, reminders, Places lookups or AI requests.
- An accelerometer window is evaluated every 15 seconds while the process runs. Stationary sampling requests 5 Hz; motion requests 25 Hz and gyroscope measurements. A significant-motion wake-up sensor, when present, starts a bounded active interval. A partial wake lock expires after 65 seconds and is renewed only while the active interval persists. It is released when idle and when monitoring stops. Phones without supported wake-up sensors can still have screen-off gaps.
- Rules produce provisional STILL (phone stillness), ON_FOOT (at least three hardware step detections), IN_VEHICLE (recent GPS speed at least 5 m/s), or UNKNOWN. These are deliberately untrained rules, not calibrated probabilities. Phone placement and walking/running/cycling ambiguities require user labels and evaluation before promotion. A person without their phone is not observable.
- A usable window requires at least 40 acceleration samples over at least eight seconds, no gap above two seconds, and a final sample no older than two seconds. Old, missing or discontinuous data stays UNKNOWN. The 15-second window cadence is not a guaranteed activity transition latency. Local delivery delay of zero describes production of the diagnostic record, not instantaneous detection.
- Google observations now preserve boot identity and monotonic observation/receipt times; context uploads record upload timing. Callback delay and upload delay can be assessed separately without wall-clock changes confusing the comparison.
- A bounded local SQLite store retains real GPS fixes and compact diagnostic windows for 24 hours on the current boot, capped at 12,000 fixes and 6,000 diagnostic rows. It stores no fabricated locations. Fixes are retained before checkpoint deduplication. A delayed event can use a same-boot fix measured within two minutes of its original monotonic time. Reboots discard incompatible local history; already uploaded cloud diagnostics remain.
- Activity samples receive the same immediate five-second capture attempt as transitions, with a durable fallback. Unavailable or inaccurate fixes can retry up to three worker attempts while the event is at most 90 seconds old. Permission failures and old events are not retried indefinitely. Concurrent stale worker failures cannot erase an existing valid location.
- Diagnostics upload in bounded batches through `/motion-diagnostics`; successful durable writes acknowledge stable IDs. An unavailable/older backend leaves the local data intact. This endpoint uses the application's existing user identity dependency; the current personal app uses a fixed local identity, not multi-account authentication.

## Label and evaluate

Open **Settings → Activity & location → Motion monitoring**. Choose the actual activity and phone placement, start a label, and finish it when that activity ends. Discard incorrect labels. Completed labels cover observed intervals only, up to two hours, and are stored separately from ordinary activity history. Leaving the screen discards an unfinished label.

Collect examples with the screen on and off, in a pocket/hand/bag and during stationary periods, walking, running, cycling and vehicle trips. Copy monitoring history before the 24-hour local retention expires, or read the cloud diagnostic endpoint for the desired day. Save the JSON as `history.json`, then run:

```powershell
cd C:\Users\sampa\Dev\Jarvis\backend
.venv\Scripts\python.exe -m scripts.evaluate_motion history.json
```

The evaluator reports coverage, confusion, accuracy including UNKNOWN, accuracy when classified, and callback/upload latency distributions separately for Google and local observations. It uses monotonic same-boot user annotations, excludes overlapping labels and windows crossing annotation boundaries, and maps walking/running to the broader ON_FOOT category for this baseline. These are observation-weighted comparisons: different detector sampling rates mean they are not a paired experiment or continuous duration measurements.

## Model training and promotion

No trained model is claimed or automatically fitted to its own predictions. Once labelled sessions exist, prepare an independent training/validation/test split by whole session or day (never randomly split overlapping windows). Include different placements and vehicle types. Start with a compact classifier over the recorded motion, step, gyro and speed features; expand raw/window features if the coarse baseline cannot separate target classes. Convert a validated model to an on-device runtime such as LiteRT. Personalization uses explicit user-labelled examples.

Compare false transitions per hour, class precision/recall, unknown coverage, true transition latency, missed sensor windows and battery use during equivalent unplugged screen-off sessions. Do not enable reminder/journey control until these measurements meet agreed targets. A model cannot recover measurements the OS never delivered, and training cannot by itself repair scheduling delays.

## Validation

Native tests cover missing/old/batched sensors, invalid samples, provisional foot/vehicle candidates, clock shifts, boot isolation and retry limits. Backend tests verify bounded schema validation, durable acknowledgement, separate storage, annotation validity and evaluation semantics. Widget tests verify labels are saved only on completion and discarded labels never become ground truth. The release APK and a short real-device screen-off check are the final implementation checks; long-term battery and accuracy remain an empirical evaluation step.

Completed on 12 October: 26 Android unit tests, 36 backend regression tests and two widget tests passed. Flutter static analysis for the new screen and its tests found no issues. The release APK was installed with app data preserved. Foreground monitoring resumed after the user opened Jarvis; live sensor windows had usable coverage and real phone diagnostic uploads reached the new endpoint. Backend revision `jarvis-backend-00123-bef` passed health/schema/diagnostic-read checks before receiving traffic; the existing INR 50 daily AI budget and conversation-recall schema remained intact.

The previous backend image had reached Docker's layer-depth limit. Deployment flattened its immutable filesystem and preserved its runtime configuration, then applied only the new telemetry modules, router inclusion, timing persistence and a narrow deployed-schema patch. Unrelated working-tree backend changes were excluded.

Observed validation was with the phone awake and USB powered. An initial launch encountered a Health Connect binder-death exception; reopening recovered and the monitoring process subsequently produced real observations. This was not a motion-detector exception. An unplugged, sustained screen-off battery/accuracy experiment and trained-model promotion have not yet been completed.
