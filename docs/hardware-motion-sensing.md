# Hardware-triggered sensing

When monitoring is enabled, native wake-up motion/significant-motion and step-detector callbacks can start context collection before Google classifies the activity. The step detector explicitly prefers its wake-up variant. Hardware triggers enter the existing durable queue as UNKNOWN context checkpoints, not fabricated WALKING transitions. Google transitions and qualified samples remain authoritative activity evidence; existing reminder confirmation requirements still apply.

On phones with supported wake-up hardware, idle accelerometer/gyro sampling, periodic location subscriptions and Google activity sampling stop. Motion starts an immediate location attempt, a moving location subscription and 30-second Google activity samples. Consecutive steps extend the same collection period without a cooldown. Local diagnostic classification still uses 15-second windows; it does not delay the hardware callback's capture. After approximately 60 seconds without local movement, active local sampling stops; fresh Google movement can keep location/activity collection running. The existing foreground-service reconciliation and 15-minute queue recovery remain. Recovery does not create idle GPS work. Devices lacking these wake-up sensors retain the previous polling fallback.

No new pickup cooldown, wakeup quota or GPS-attempt quota is introduced. Existing provider request timeouts, event-freshness validation and durable retry policies remain. Those prevent hanging requests and assigning present-day fixes to old events.

## Wi-Fi

Calibrated network identities come from saved-origin evidence in active departure reminder state (`home_wifi_id` plus `origin_seen`). Nearby arbitrary Wi-Fi does not establish a saved place. If the connected identity matches and RSSI is at least -67 dBm (and valid), requests use balanced-power location; disconnected, weak, unknown or unavailable Wi-Fi allows high-accuracy moving requests. The signal cutoff is an initial heuristic, not a measured flat boundary. Accuracy is reconsidered on joins/leaves and during service reconciliation. Connection snapshots already preserve RSSI with hashed network identities.

This changes location power preference, not coordinates, floor labels or departure truth. Known Wi-Fi can extend into a staircase, terrace or outdoors. Real location observations and the existing matcher can still supply conflicting evidence. No synthetic location is assigned from Wi-Fi and no satellite/provider behavior changes.

## Height and gravity

The inspected 2201116PI phone exposes gravity, linear acceleration, gyro, motion and wake-up step sensors, but no pressure/barometer sensor. Gravity supplies an orientation reference for separating gravitational acceleration from movement; it does not provide practical floor-height measurements. Integrating accelerometer data into height accumulates bias/drift, and satellite altitude is not dependable for floor transitions indoors.

Floor-to-terrace recognition would require a separately evaluated inference system (labelled stairs/terrace sessions, placement variation and environmental evidence) or an additional height reference such as a barometer-equipped device. Wi-Fi signal/light changes can support a hypothesis, not independently verify a floor. This change does not claim or implement floor recognition.

## Verification

JVM sensing-policy scenarios cover immediate collection before GAR, return to idle, repeated reactivation without a cooldown, unsupported-hardware fallback, and unknown/weak/invalid Wi-Fi. Device sensor presence was inspected separately. A successful build/unit suite does not establish screen-off latency, missed-step rate or battery performance; those need a labelled physical experiment with monitoring enabled.

On 31 October 2026, all 49 native JVM tests passed and the debug APK built successfully against the documented development endpoint. It was installed with `adb install -r`. Post-install checks found unchanged power/monitoring preferences (both off), no running Jarvis process, SQLite `quick_check=ok`, and unchanged reminder/note/place/chat/context-history row counts. No backend deployment or live movement trial was performed. Local verification evidence is in ignored `tests/coding_agent_artifacts/diagnostics/hardware-sensing-install-verification.json` and `tests/coding_agent_artifacts/harness/hardware-sensing-jvm.json`.

Android references: [motion/gravity sensors](https://developer.android.com/develop/sensors-and-location/sensors/sensors_motion), [wake-up sensor types](https://source.android.com/docs/core/interaction/sensors/sensor-types), and [pressure-based relative altitude](https://developer.android.com/reference/android/hardware/SensorManager#getAltitude(float,float)).
