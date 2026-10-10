# Jarvis architecture: video transcript

English narration synthesized locally with Microsoft Zira.

## Jarvis: the whole project

Jarvis is a personal Android assistant that combines chat with observations from your phone. It can manage notes and reminders, explain sampled activity history, work with Google Calendar, and retrieve information from Drive files. Think of it as a phone application connected to a modular Python backend, with a separate embedding service and an indexing worker. This explanation follows the current local code. It does not verify which revision is running in the cloud.

## The phone has two layers

The visible interface is built with Flutter. Its main tabs are Chat, Activity, Reminders, Notes, and Settings. Singleton services and Flutter notifiers manage transport, local data, sensors and Google connections. Underneath, Kotlin handles Android capabilities that need to work when Flutter is closed: activity recognition, background location, upload workers, push messages and reminder alarms. Method channels connect these layers. The frontend is therefore more than the screens. Native Android code is an essential part of its reliability.

## Offline storage and telemetry

The phone stores app records in a local SQLite database. Flutter telemetry also has a SQLite outbox. Native background events use a different queue: a JSON array committed to SharedPreferences. This differs from the README, which describes that native queue as SQLite. WorkManager uploads queued events and retries failures while preserving their identifiers. Explicit sensor recordings produce CSV files and JSON summaries. These recordings are distinct from the journey sessions and activity intervals reconstructed by the backend. Offline capture is supported, but cloud chat and integrations still need connectivity.

## FastAPI coordinates the work

The backend uses FastAPI to expose telemetry, commands, reminders, notes, synchronization, recording backups and file operations. Chat progress uses server sent events, with request status and reconnect support. This is not a WebSocket design. The API invokes a cached LangGraph workflow and deterministic domain services. Tier one and tier two are reasoning paths inside the same application, not independent deployed microservices. Blocking graph and cloud operations are moved to worker threads in important async endpoints. A separate embedding service and an indexing job handle file retrieval workloads.

## Two reasoning paths

Every graph run begins with normalization and context loading. Context events go through an evidence gate. Ordinary sparse observations can use the deterministic reducer directly, while ambiguous feature bearing telemetry can invoke tier one and its tools. Commands go through intent routing. Greetings have a fast path; other requests enter tier two and its tool loop. Chat now loads context on demand, so a file question does not automatically fetch GPS or nearby places. Both branches eventually persist their results. Journey statuses are Created, Active, Paused, Resumed, Completed and Expired; parking and shop context are separate concepts.

## Where each kind of data lives

There is no PostgreSQL or MySQL server in this checkout. SQLite holds device data and backend local state. Firestore holds cloud records, context memory, command requests, notifications, budgets and indexing metadata. Cloud Storage holds recording backups and staged imports. Chroma stores derived file chunks and their vectors. Firestore does not have one uniform layout: reminders and chats use top level collections with user fields, while context and requests use collections under a user document. Some task tools write only to backend SQLite, so their cloud durability needs attention. A local table does not automatically imply a durable cloud copy.

## Chat and Calendar execution

A command starts with a stable request identifier and a Firestore claim. Fingerprints reject reuse of an identifier for a different message, and leases prevent competing command execution. Cloud Tasks can continue the work when the phone connection ends. The device receives progress and proposals through the command stream. For Calendar writes, the phone shows a concrete proposal, obtains approval, calls Google using its own authorization, and returns the result. ETags and receipts protect against changed events and uncertain repeat writes. Ordinary requested notes and reminders are currently allowlisted without a second approval dialog. Older documentation says otherwise.

## Context becomes a reminder

A background phone event is persisted before reminder rules are evaluated. Immediate context alerts require fresh matching evidence; the ingestion route uses a five minute freshness window. Older uploads can still improve history without triggering an immediate alert. A one shot reminder and its notification outbox entry are committed together in Firestore. Push delivery or polling brings the alert to the phone, and acknowledgement prevents ordinary duplicates. Activity delay reminders use durable timer state and task callbacks. Sensor gaps remain gaps. The timeline does not prove continuous exercise, and Android scheduling can delay background work.

## Drive search is a separate pipeline

Drive retrieval has its own pipeline. The phone downloads or exports an authorized source, registers metadata, and uploads bytes to private staging. A leased cloud indexing job reads formats, creates bounded chunks, and asks the separate embedding service for vectors. The code pins the model revision and checks that vectors have seven hundred and sixty eight dimensions. Chroma stores the derived evidence with owner, account and source version metadata. Queries embed the question and retrieve filtered evidence. Successful staged sources are deleted; failed ones remain for retry. Large imports also have a local bulk workflow. Direct multimodal file analysis is another path, not the same as indexing.

## The main architectural risks

The largest boundary is identity. The backend currently returns the same local user for every caller; the mobile user header is not authenticated account identity. File capabilities and Calendar sessions protect specific paths, but they do not isolate all API data. Synchronization also has important gaps. The push route can acknowledge records without confirming Firestore persistence. Some cloud readers convert errors into empty lists, while the phone interprets missing remote records as deletions. Additional concerns include instance local tasks, full collection scans, concurrent session updates, an unbounded direct index upload path, and different frontend and native backend URLs.

## Reliability, cost and next decisions

The project already has useful reliability mechanisms: stable event and request IDs, command leases, transactional notifications, cautious write receipts, and selective model use. The AI allowance uses durable reservations in Cloud Run and resets by Indian time, but this does not cap indexing, compute, storage or database costs. Before expanding the system, decide whether it is single user or multi user, choose an authoritative durable store for every entity, and define exactly what a sync acknowledgement guarantees. Then test outages, retries, races and permission denial. The companion report provides detailed diagrams, source evidence and a prioritized action list.
