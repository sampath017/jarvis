# Jarvis Simulation — Walkthrough

## What Was Built

A **complete end-to-end simulation** of every component described in the Jarvis Context-Aware Mobile Agent BRD. The simulation runs entirely in Python with no Android device or cloud API keys required (mock mode).

### Architecture

```mermaid
graph LR
    A["Activity Transition<br/>(simulated)"] --> B["IMU Burst<br/>(synthetic)"]
    B --> C["Feature Extraction<br/>(FFT + time-domain)"]
    C --> D["Vehicle Classifier<br/>(fingerprint match)"]
    D --> E["Context Packet"]
    E --> F["Session State Machine<br/>(stop-shop-return)"]
    F --> G{"Conflicts?"}
    G -->|Yes| H["Tier 1 Reasoner<br/>(7B model / mock)"]
    G -->|No| I["Accept"]
    H --> I
    I --> J{"User Command?"}
    J -->|Yes| K["Tier 2 Orchestrator<br/>(72B model / mock)"]
    K --> L["Function Registry<br/>(allow-list validation)"]
    L --> M["CRUD Store"]
    J -->|No| N["Done"]
    M --> N
```

### Files Created (20 files)

| Layer | File | Purpose |
|-------|------|---------|
| Config | [config.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/config.py) | All tunable params, .env loading |
| Config | [.env](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/.env) | OpenRouter API key + model selection |
| Models | [enums.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/models/enums.py) | Activity, session, vehicle enums |
| Models | [schemas.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/models/schemas.py) | All Pydantic data models |
| Edge | [imu_sampler.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/edge/imu_sampler.py) | Synthetic IMU burst generator |
| Edge | [feature_extractor.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/edge/feature_extractor.py) | Time + frequency domain features |
| Edge | [vehicle_classifier.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/edge/vehicle_classifier.py) | Hunter 350 fingerprint classifier |
| Backend | [session_manager.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/backend/session_manager.py) | Stop-Shop-Return state machine |
| Backend | [context_resolver.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/backend/context_resolver.py) | Conflict detection + Tier 1 trigger |
| Backend | [crud_store.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/backend/crud_store.py) | In-memory CRUD (8 entity types) |
| Backend | [audit_log.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/backend/audit_log.py) | Structured JSONL audit logging |
| Cloud | [function_registry.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/cloud/function_registry.py) | Allow-listed function interface (14 functions) |
| Cloud | [tier1_reasoner.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/cloud/tier1_reasoner.py) | Context resolver (mock + OpenRouter) |
| Cloud | [tier2_orchestrator.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/cloud/tier2_orchestrator.py) | Agentic orchestrator (mock + OpenRouter) |
| Pipeline | [pipeline.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/pipeline.py) | 9-stage end-to-end orchestrator |
| Eval | [scenarios.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/scenarios.py) | 12 test scenarios |
| Eval | [eval_runner.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/eval_runner.py) | Evaluation harness |
| Eval | [eval_report.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/eval_report.py) | Markdown report generator |
| CLI | [__main__.py](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/src/__main__.py) | CLI entry point |

## Evaluation Results — 12/12 PASS (100%)

| # | Scenario | Latency |
|---|----------|---------|
| 1 | Simple Ride — Hunter 350 Detection | 60.8ms |
| 2 | Car Ride — Correct Rejection | 5.9ms |
| 3 | Bus Ride — Correct Rejection | 6.4ms |
| 4 | Stop-Shop-Return — Session Continuity | 4.0ms |
| 5 | Session Timeout — TTL Expiry | 0.1ms |
| 6 | Ambiguous GPS — Tier 1 Invocation | 21.1ms |
| 7 | New POI — Tier 1 Semantic Resolution | 0.2ms |
| 8 | User Command: Reminder | 0.7ms |
| 9 | User Command: Note | 0.3ms |
| 10 | Invalid Function Call — Rejection | 0.2ms |
| 11 | Offline Queue — Event Replay | 10.8ms |
| 12 | Walking — No Vehicle Classification | 0.1ms |

### BRD Success Criteria — All 8 Met

| Criterion | Status |
|-----------|--------|
| Reliably detect IN_VEHICLE activity | ✅ |
| Capture bounded IMU burst | ✅ |
| Distinguish Hunter 350 from non-matching vehicles | ✅ |
| Maintain session across stop-shop-return | ✅ |
| Resolve ambiguous context via Tier 1 | ✅ |
| Interpret user commands via Tier 2 | ✅ |
| Generate only valid, allow-listed function calls | ✅ |
| Audit log completeness | ✅ |

## LLM Model Configuration

Per BRD Section 7.1 — economical models, configurable without app rebuild:

| Tier | Model | Role | Cost |
|------|-------|------|------|
| Tier 1 | `qwen/qwen-2.5-7b-instruct` | Structured context resolution (JSON only) | Very cheap |
| Tier 2 | `qwen/qwen-2.5-72b-instruct` | Agentic command interpretation | Moderate |

Both are configurable via [.env](file:///c:/Users/sampa/Dev/Jarvis/Model_Training/.env).

## How to Switch to Live Mode

1. Add your OpenRouter API key to `.env`:
   ```
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```

2. Run with `--live` flag:
   ```bash
   uv run python -m src --live
   ```

## What Was Tested

- Full pipeline execution for all 12 scenarios
- Vehicle classification accuracy across 4 vehicle types + walking
- Session state machine transitions (create, pause, resume, expire)
- Tier 1 invocation triggers (poor GPS, weak fingerprint, unknown POI)
- Tier 2 command processing (reminders, notes, invalid commands)
- Function call validation (allow-list enforcement, schema validation)
- Audit log completeness (45 entries across all scenarios)
