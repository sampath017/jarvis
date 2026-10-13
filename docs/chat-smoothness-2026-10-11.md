# Chat typing and time display

Typing in the message box previously called `setState` on the entire chat screen
for every edit. This rebuilt the conversation, history drawer and header even
when only the draft or keyboard composition had changed. The send button now
listens directly to the text controller; the text field manages its own edits.

Request progress now uses a separate notifier that rebuilds only the progress
bubble. Duplicate updates are ignored, and elapsed-time-only updates no longer
trigger automatic scrolling. Scroll requests within one frame are coalesced and
the scroll animation is 160 ms. Service notifications rebuild the chat screen
only when its online status changes.

The connected phone was running a debuggable APK before this release. The new
APK uses Flutter release mode. No measured end-to-end input latency is claimed;
the regression check verifies that editing and IME composition no longer rebuild
the chat header, while send availability and drafts across tab changes still work.

Time labels no longer append IST in mobile timestamps, usage notification text,
settings copy, deterministic activity reports and budget-reset messages. The
conversation agent is instructed to omit timezone labels unless asked about
timezones. Time conversion and day boundaries continue to use Asia/Kolkata.

## Usage versus battery

Jarvis's usage report reconstructs foreground screen time from Android activity,
screen and lock events. It excludes the launcher, lock screen and background
audio/downloads. It does not measure per-app battery consumption. Android's
Battery settings include energy attributed to background work and may use a
different reporting window. Compare screen-time totals with Digital Wellbeing
for the same day; exact agreement is not guaranteed because accounting rules,
retained events and report cutoffs can differ. The scheduled Jarvis report ends
at 23:00, while an on-demand report covers midnight through the current time.

## Validation

- 37 backend tests passed (activity reports, budget limits, complete replies).
- 11 focused Flutter tests passed (layout and typing, progress, time conversion,
  command event handling and usage reports).
- Flutter static analysis: no issues.
- `git diff --check`: no whitespace errors.

## Deployment verification

- Backend: `jarvis-backend-00114-dit`, 100% traffic in `asia-south1`.
  The candidate health check passed before promotion. The production `/health`
  endpoint used by the phone also returned `healthy` after promotion.
- Cloud Build: `5a4849d1-2188-4c93-b5bd-d6946ea5544a`, successful.
- Previous serving revision: `jarvis-backend-00091-ck5`.
- Backend image digest:
  `sha256:fca3cfa8616efacd6c574da05e93ccc492369590c73179c345681b730f3f6c05`.
- Android: `flutter build apk --release --no-pub` passed. Installed with
  `adb install -r` on the connected POCO without clearing app data, at
  2026-10-11 15:36:06 phone time. Launch returned `Status: ok`.
- APK: `mobile/build/app/outputs/flutter-apk/app-release.apk`.
  SHA-256: `3679fa56065faef5adcb2cf187ce145b570ceb635b4872ebf966f61cb560ecd0`.
- Installed package flags no longer include `DEBUGGABLE`. The running
  `MonitoringService` is foreground with notification ID 1002.
- The inspected startup log contained no matching fatal, unhandled, SQLite,
  missing-plugin, missing-class or missing-method errors. This is a startup smoke
  check, not a measured frame-time or battery-life benchmark.

All source changes remain uncommitted.
