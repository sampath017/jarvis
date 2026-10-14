# Departure reminders and satellite imagery

Departure policy version 2 combines timestamped location, verified movement,
home-network observations and an optional satellite footprint. It does not use a
fixed 200 m circle or require a map editor.

## Setup and image display

`inspect_satellite_view` returns a `satellite-map` chat card. The phone requests
the actual, complete Google Maps satellite PNG through `/mobile/satellite-map`;
the key stays on the backend, provider attribution remains visible, and image
bytes stay transient. The card can overlay an estimated outline. Departure
reminders also expose a read-only Satellite view action.

At reminder creation, or foreground refresh through
`/mobile/departure-boundaries`, a bounded visual call can identify a visible
building/fence outline around the saved Home anchor. It returns image-pixel
vertices, confidence and uncertainty. Web Mercator projection converts validated
vertices using the exact image center, zoom, size and scale. Self-intersecting,
incomplete, off-image, low-confidence or ambiguous outlines are rejected.
An estimate is supporting evidence, never a surveyed fence or a way to locate
an individual flat's interior doorway.

If the close view is unclear, one wider zoom-18 view is tried, with matching
projection and display metadata. No further visual retries run on that setup.

Only estimated coordinates and provenance are stored in the saved place's
SQLite `boundary_json` column. Successful estimates refresh after seven days;
unclear/unavailable results retry after six hours. Foreground setup handles at
most one uncached origin per request. Sensor events do not call vision.
Existing active departure policies upgrade in place; completed/deleted records
and their history are preserved.

## Evaluation

1. Require a fresh event and a location within two minutes of its observation
   time, including a fix obtained shortly after the event. Android moving
   transitions try a new fix before reusing an older indoor measurement.
2. Observe Home presence with a location confidently inside the footprint, or
   an accurate fix at the saved anchor accompanied by connected Wi-Fi. Keep
   the better Home reference when later indoor fixes are less accurate.
3. Record verified walking/on-foot/running evidence for at most two minutes.
   Cached activity names and shadow motion candidates cannot establish it.
4. A footprint crossing must exceed both reported GPS uncertainty and estimated
   outline uncertainty. Alternatively, calibrated home Wi-Fi loss plus clear
   displacement beyond both location uncertainties can support departure when
   the footprint cannot be established. Wi-Fi disconnection alone never matches.
5. Fresh evidence that calibrated home Wi-Fi is no longer connected supports
   confirmation with two different, increasing GPS fixes spanning five seconds.
   If Wi-Fi is unknown or still reaches outdoors, require the footprint and
   three fixes spanning ten seconds. Unknown/disabled Wi-Fi is not a disconnect.
6. Uncertain positions reset candidate confirmation. Boundary changes reset
   continuity. The original one-shot reminder transaction controls idempotency
   and preserves its requested call/alarm/notification delivery.

SQL reminder state records the latest evaluation reason and supporting evidence.
Android sends this state on relevant requests and commits returned changes before
acknowledging the event. Stale observations remain history and never ring old
reminders retroactively.

## Verification and limits

Synthetic regressions cover geometry, uncertainty, Wi-Fi loss/absence, indoor
walking, repeated/older fixes, timestamp offsets, one-shot delivery and separate
SQL requests. Image checks cover request validation, projection, visual refusal,
bounded setup/cache, data preservation and mobile rendering. Real provider
output is an additional live check, not established by mocked provider tests.

The locally copied October 29 outing, evaluated offline with the new policy and
no assumed satellite footprint, first matched at 00:24:12 IST. The old policy
never matched. This counterfactual used a private local copy, not a replay to
the backend or a retroactive alert. It confirms available departure evidence
roughly three minutes after walking began, not exact doorway timing.

Satellite imagery does not improve GPS precision. Sparse fixes, indoor coverage,
Android scheduling and uncertainty can delay or prevent confirmation.

## Development verification, 29 October 2026

The integration passed 619 full backend cases, 179 Flutter cases and 44 native
JVM cases. Later provider/matcher hardening passed 79 focused satellite/provider
cases and 67 departure/continuity/card cases; these overlap the full suite and
must not be added as a unique-case total. The final zoom metadata has a separate
targeted Flutter regression.

The debug APK was installed with existing data retained. Phone SQLite reports
schema 10 and a successful integrity check. The active departure reminder uses
policy version 2 with in-app call delivery and no policy radius. Notes, existing
messages/sessions and inactive reminders were checked against the pre-install
snapshot. Actual Google imagery was verified through the debug API and on the
phone under Apps → Reminders → Satellite view. These checks do not substitute
for a new physical departure after installation.

The final live vision call completed through debug revision 00200. Home's
zoom-19 outline was cropped; the zoom-18 result failed geometry/visibility
validation. No footprint was saved. The image remains viewable and the calibrated
GPS/walking/home-Wi-Fi path remains active. A successful inferred Home boundary
has not been claimed or manually supplied. The final phone check reports zero
queued events and zero upload failures; production remains on revision 00189.
