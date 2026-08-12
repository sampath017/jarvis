# Jarvis Client Simulator

This standalone client simulates realistic Android client traffic (activity transitions, GPS positions, IMU feature summaries, and natural language user commands) against the Jarvis backend API.

---

## Directory Structure

```
simulation/
├── src/
│   ├── __init__.py
│   ├── constants.py       # Physics constants, coordinate presets (Home, Gym, Office, Park, Store)
│   ├── models.py          # ActivityEvent, ChatTurn, HttpResult, VibrationProfile, VIBRATION_PROFILES
│   ├── features.py        # IMU synthetic burst generation & compact feature extraction math
│   ├── client.py          # Standard-library HTTP client and terminal execution formatters
│   ├── scenarios.py       # 5 comprehensive test sessions + backward-compatible builders
│   └── main.py            # CLI entry point and session dispatcher
├── README.md              # Documentation
├── pyproject.toml
└── uv.lock
```

---

## Available 10+ Minute Simulation Sessions

| Scenario | Virtual Time | Description & Subsystems Tested |
|:---|:---|:---|
| `morning-commute` | ~18 min | **Tier 1 & Mobility**: Normal ride start, low-confidence fingerprint, stationary GPS conflict, poor GPS accuracy (85m), parking pause, idempotency, and destination dwelling. |
| `life-admin-full` | ~22 min | **Tier 2 LLM & Personal Automation**: Interleaved natural language commands (`POST /commands`) and context events (`POST /context-events`). Tests notes CRUD, geofence & activity reminders, context rules (`APPEND_NOTE`, `NOTIFY`), outbox notifications, note updates, reminder completion, and rule listing. |
| `session-lifecycle` | ~60 min | **Session TTL & Lifecycle**: Ride start, session continuation, parking pause, dwell, resume within 30-min TTL, second pause, extended 35-min dwell exceeding 30-min TTL (forces session expiration and new session start), and final parking. |
| `edge-cases-extended` | ~15 min | **Vehicle Classes & Conflicts**: Tests all vibration profiles (`HUNTER_350`, `CAR`, `BUS`, `OTHER_MOTORCYCLE`), definitive negative (`NOT_VEHICLE`), low confidence, and stationary GPS conflicts. |
| `context-rules-deep` | ~20 min | **Automation Actions & Triggers**: Exercises all 3 context rule action types (`NOTIFY`, `APPEND_NOTE`, `UPDATE_REMINDER`), trigger types (`GEOFENCE_ENTER`, `ACTIVITY_ENTER`), recurring rules, `one_shot` rule disabling, and geofence exit/re-entry. |

---

## Usage

### 1. List Available Sessions

```bash
cd simulation
python src/main.py --list-scenarios
```

### 2. Preview Payloads (Dry Run)

```bash
python src/main.py --scenario morning-commute --dry-run
python src/main.py --scenario life-admin-full --dry-run
```

### 3. Run Live Against Backend

1. **Start the backend server** (in one terminal):
   ```bash
   cd backend
   python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8080
   ```

2. **Execute the simulation session** (in another terminal):
   ```bash
   cd simulation
   python src/main.py --scenario morning-commute --base-url http://127.0.0.1:8080
   ```

   For chat sessions (Tier 2 LLM interactions), a minimum delay of 2.1 seconds between turns is automatically enforced to respect backend rate limits:
   ```bash
   python src/main.py --scenario life-admin-full --base-url http://127.0.0.1:8080
   ```

---

## Design Principles

- **Zero Heavy Dependencies**: Uses standard library modules (`urllib`, `dataclasses`, `json`, `math`).
- **Compact Sensor Features**: Synthesizes transient 50 Hz IMU bursts in memory and extracts only the compact `feature_summary` DTO accepted by the backend.
- **Virtual Time**: Elapsed time is represented via `occurred_at` offsets, allowing long scenarios (e.g. 60 min) to be validated instantly while preserving timestamp semantics.
