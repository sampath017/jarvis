# Jarvis phone power switch

This guide describes current behavior; the filename is retained for existing links.

Settings controls a durable phone-owned master switch. It works offline and
survives app closure, updates and reboot. Off retains saved records and Google
connection choices while stopping Jarvis work on the device.

## Off and resume

Native `JarvisPower.setEnabled()` commits the boundary before cancellation. It
closes tracked HTTP connections and location requests, unregisters activity and
location monitoring, stops foreground recording/monitoring services, pauses local
alarms/usage reporting, cancels WorkManager jobs and clears current notifications.
Flutter closes its tracked connections, stops timers/sensors and shows Settings
on an Off launch.

On restores permitted usage work, weekly Drive backup, alarms and the saved
monitoring choice. Launch reads the durable setting without depending on API
availability, so local records remain usable offline. The current switch does
not make a project-wide cloud shutdown request or prove external billing stopped.
Historical names such as `cloudConfirmed` in the local bridge are not evidence of
an active cloud control plane.

Already accepted external writes/model requests cannot be reversed by closing a
connection. Independent clients, retained cloud services/resources and build work
can still have costs. Local Off is not a cloud project billing cap.

## Coverage history

Real switch changes store off/on intervals with the switch preference in one
commit. `MobileStore.historyContext()` includes overlapping intervals as explicit
`JARVIS_OFF_INTERVAL` evidence, preserving original boundaries. Historical reports
can explain the monitoring gap; they cannot infer the user's activity while Jarvis
was off. Gaps without switch evidence remain unexplained.

Sources: `mobile/lib/services/runtime_power_service.dart`,
`mobile/lib/services/power_http.dart`, `JarvisPower.kt`,
`mobile/lib/services/mobile_store.dart` and `backend/src/backend/power_history.py`.
Relevant tests cover local power gating and historical off-interval clipping;
real phone/OEM lifecycle behavior still needs device verification.
