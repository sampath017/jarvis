# File memory, indexing and native analysis

## Ownership and authorization

Ordinary chat attachments are copied into app-private `attachments/` files on the
phone, with local metadata and receipts. The current attachment/processing limit
is 128 MB. Sending an attachment makes it available to that chat; an explicit
Drive-save request copies or promotes it to the connected account's managed
`Jarvis/Saved Files` folder. Existing Drive originals remain at their current IDs.

Google authorization and access tokens stay on Android. The app requests
`drive.readonly` for discovery, `drive.file` for managed writes and
`forms.responses.readonly` for Forms responses. Connection restoration silently
reuses an existing grant only when allowed, verifies API access before saving it,
and does not open consent without user interaction. An explicit disconnect stops
restoration until the user reconnects.

The file capability scopes API/index requests independently of the personal
backend's fixed local user. It is not cross-device account authentication.
Disconnecting Google prevents further authorized Drive operations; it does not
delete existing originals or local attachment metadata.

## Indexing and retrieval

Android reads authorized sources and submits bounded bytes for temporary
processing. File catalog, scan progress and index receipts stay on the phone.
There is no bucket-staging or durable cloud indexing-job requirement in the
production mobile API.

Readers cover text/PDF, Office formats, archives, supported media and selected
binary/database metadata. They return content, partial coverage or metadata-only
coverage with a reason. Unknown, encrypted, damaged or inaccessible sources must
not be described as fully read. Office readers preserve available tables, sheets,
notes and embedded content; media locators are not transcripts.

The separate CPU embedding service runs pinned `google/embeddinggemma-2` and
returns normalized 768-dimensional vectors. Chroma collection
`jarvis-drive-eg2-768-v1` stores chunks/vectors plus owner, account, source version,
digest, generation, coverage and locator metadata. Identical complete sources can
reuse vectors. New complete generations replace older ones without exposing
failed partial generations as complete search results.

Search combines authorized Drive filename/full-text discovery with indexed
semantic candidates. Android rechecks current access and file versions before
requesting passages for the verified file set. The information need is kept
separate from discovery keywords. Selected passages require model synthesis and
are untrusted evidence, never instructions. A filename match or incomplete index
cannot prove a file's contents or absence.

Query embeddings use a shorter timeout than indexing; cold starts and larger
media can exceed interactive latency expectations. An unavailable index can fall
back to authorized Drive search with an explicit coverage notice. Source code
does not establish the live service's region, resources or revision.

## Original-file analysis and chat flow

The agent chooses search, analysis and explicit save tools. It can batch two
independent file reads through one device action while writes remain ordered.
New attachments initially use a smaller file-routing prompt/tool set; mixed
requests can continue into the shared assistant runtime.

Native PDF/image/video analysis sends at most 20 MB of source bytes through the
API to the configured model provider. Other supported sources use parsing/indexed
passages. The backend keeps temporary source data for processing rather than a
permanent application-record copy. Provider handling follows the configured
provider policies. Analysis receipts prevent automatic paid replay after an
uncertain response; partial results require explicit limitations and follow-up.

The phone stores the conversation's final derived answer. Chat renders Markdown,
tables, source links and validated chart data. It does not execute file/page HTML,
JavaScript, macros or embedded instructions.

Sources: `mobile/lib/services/google_drive_service.dart`,
`backend/src/api/routers/file_memories.py`, `backend/src/api/routers/drive_index.py`,
`backend/src/services/drive_index.py`, `backend/src/services/file_readers.py`, and
`backend/models/embedding/app.py`. See [storage](android-local-storage.md) and
[chat formatting](chat-formatting.md).
