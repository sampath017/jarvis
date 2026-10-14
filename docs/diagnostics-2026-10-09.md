# Activity coverage and compute-cost diagnostic lessons

The October 9 investigation concerned a reported bike ride for which the phone
had no corresponding observations. An unmatched WALKING EXIT after the gap had
been incorrectly interpreted as a walking span. Successful uploads around a gap
do not establish what happened inside it or why Android failed to deliver data.
A user-reported correction can be retained with attribution, without invented
sensor evidence or GPS.

Current monitoring combines Play Services transitions, repeated confident samples,
adaptive location capture, a durable local queue and native workers. Cached labels
and unmatched exits do not establish activity spans; stale or uncertain samples
remain UNKNOWN. Android scheduling, force-stop, missing permissions and power
state can interrupt coverage. Device/process evidence is required before naming
the cause of a specific gap.

See [background context delivery](background-context-delivery.md) for current
frequencies, retry/staleness controls and diagnostics, and
[session continuity](session-fragmentation-2026-10-10.md) for historical coverage
interpretation. The current deployment is not established by old revision IDs or
past successful probes.

The same investigation found that document extraction/indexing and embedding
inference accounted for most measured CPU allocation in the inspected period.
That was an allocation observation, not a precise attribution of the net bill.
Extraction waiting for inference can still consume runtime resources; scale-to-zero
does not eliminate storage or active-job costs.

For a large local import, review `backend/scripts/local_bulk_index.py` and
[embedding setup](../backend/models/embedding/README.md). Validate model/revision
compatibility and source scope before running it. The current mobile path keeps
index catalog/progress on the phone and document chunks/vectors in Chroma;
historical staging/job deployment details do not define today's processing path.
No resource, data, model or deployment changes are performed by this document.
