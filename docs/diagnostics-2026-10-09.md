# Jarvis activity and cost diagnostics — October 9, 2026

## Missed bike ride

The user reported a bike ride from 00:50 to 01:00 IST on October 9. The phone's
last observation before the ride was 00:41:09. The next transition was 01:01:33:
an unmatched WALKING EXIT alongside STILL ENTER. There were no observations
covering the ride. The earlier chat incorrectly interpreted that exit as a
walking span and narrowed the missing period. Successful uploads before and
after the gap do not establish why Android delivered no events during it.
Available process-exit history showed low-memory/OEM cleaning events, but did
not retain evidence proving the cause at midnight.

The ride is now stored as a user report, 00:50–01:00 IST, without fabricated GPS
or sensor observations. Live history returns BIKE_RIDE with
`evidence_status=user_reported`, no walking span, and preserves the phone's
unobserved period. Cached state and unmatched exits cannot create spans; stale
or low-confidence samples become UNKNOWN. Phone classifications remain
classifications rather than confirmed real-world actions.

## Monitoring changes and verification

The release APK was built and installed on the POCO X4 Pro without clearing
app data. Monitoring now has its own low-power sticky foreground service,
fresh Android activity samples, adaptive location requests, durable queued
uploads and existing reboot/package-update recovery. Agreement between two
fresh samples at at least 80% confidence is required to accept a sample label.
Background native FCM requests respect the monitoring setting, deduplicate
request IDs and expire after two minutes. Their receipt is stored before slow
history enrichment.

Verified foreground monitoring and battery-optimization exemption after
installation. Backend requests returned fresh GPS with the app in the
background and with the screen off. The final deployed revision is
`jarvis-backend-00088-9bs`, ready with 100% traffic. Final verification request
`38d9522f-a202-47a5-8e4b-40e1af95a425` completed: GPS timestamp
09:18:40.600 UTC and receipt 09:18:40.944 UTC. USB was disconnected on the final
ADB check, but this network receipt succeeded independently of USB.

Forty targeted backend/local-runner tests passed during final verification.
Three Android MotionEvidence unit tests passed and the release build succeeded.
Actual classification during another bike ride has not been field-tested.
Android background delivery can be delayed; force-stopping the app in Settings
prevents FCM delivery until it is reopened. Continuous availability cannot be
guaranteed through a force-stop or a powered-off/offline phone.

## Cost finding and safeguards

The billing screenshot totals ₹256.79 net. Cloud Run shows ₹686.82 usage,
₹501.06 savings and ₹185.75 net. Other displayed costs are Cloud Build ₹44.95,
Artifact Registry ₹17.21, App Engine ₹8.72 and Cloud Storage ₹0.16.

Cloud Monitoring, October 1–9, showed approximately:

| Resource | CPU allocation |
| --- | ---: |
| Mumbai embedding service | 47.50 vCPU-hours |
| Drive index worker | 24.50 vCPU-hours |
| Main backend | 3.05 vCPU-hours |

Including older embedding services, indexing accounts for approximately 96% of
recorded CPU allocation. This supports indexing as the principal compute
driver, not a precise share of the net bill. Exact per-resource rupee allocation
was unavailable; no BigQuery billing export dataset was found. The latest index
execution lasted approximately 9 hours 10 minutes. No active execution appeared
in the ten most recent executions at final verification.

The cloud index worker is billed while it waits for embedding responses. Future
bulk imports should run both extraction and inference locally, then upload
compatible vectors to Chroma. Runtime queries and small incremental updates can
keep Cloud Run. The new local runner validates inputs without network calls by
default, requires localhost for inference, checks model compatibility and reuses
production readers/digest checks. It does not change the phone's existing cloud
bulk-scanner flow or register new file metadata. The local model was not built
or downloaded during this investigation; no bulk reindex was started.

Deployed a telemetry safeguard: frequent samples/checkpoints no longer trigger
a full-day history rebuild. Backend wake observations follow the deterministic
context path without an unnecessary model call for sparse sensor ambiguity.
Current services retain request billing and zero configured minimum instances.

See [local bulk workflow](../embedding/README.md),
[Cloud Run pricing](https://cloud.google.com/run/pricing), and
[Android FCM prerequisites](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages).
