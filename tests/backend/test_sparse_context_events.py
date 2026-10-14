"""Sparse Android events must remain usable when GPS or IMU is unavailable."""

from unittest.mock import patch
from datetime import datetime, timezone

from src.graph.builder import build_workflow
from src.graph.nodes.context_gate import ContextGateNode
from src.models.enums import SessionStatus
from src.models.schemas import SessionState
from src.services.database import DatabaseService


def _state(feature_summary=None):
    return {
        "uid": "sparse_event_test",
        "request_type": "CONTEXT_EVENT",
        "raw_request": {"event_type": "ACTIVITY_ENTER"},
        "context_packet": {
            "event_id": "evt_sparse_walking",
            "activity": "WALKING",
            "transition": "ENTER",
            "gps": None,
            "feature_summary": feature_summary,
        },
        "session": SessionState(status=SessionStatus.PAUSED).model_dump(mode="json"),
    }


def test_activity_transition_without_location_does_not_require_assessment():
    with patch("src.graph.nodes.context_gate.audit_from_state"):
        result = ContextGateNode()(_state())
    assert result == {"conflicts": [], "needs_context_assessment": False}


def test_backend_context_wake_does_not_invoke_a_model_for_sensor_ambiguity():
    state = _state()
    state['raw_request']['event_type'] = 'BACKEND_CONTEXT_REQUEST'
    state['context_packet']['activity'] = 'UNKNOWN'
    with patch('src.graph.nodes.context_gate.audit_from_state'):
        assert ContextGateNode()(state)['needs_context_assessment'] is False


def test_frequent_samples_do_not_rebuild_full_cloud_history():
    import asyncio
    from unittest.mock import Mock
    from src.api.routers.context_events import ingest_context_event
    from src.models.schemas import ContextEventRequest
    workflow = Mock()
    workflow.invoke.return_value = {'changed_records': [], 'semantic_contexts': []}
    with patch('src.api.routers.context_events.TokenBudgetGuard'), \
         patch('src.api.routers.context_events.ContextAutomationService') as automation, \
         patch('src.services.record_store.RecordStore', side_effect=AssertionError('No history rebuild per sample')):
        automation.return_value.process_context_event.return_value = []
        result = asyncio.run(ingest_context_event(ContextEventRequest(event_type='ACTIVITY_SAMPLE'), 'u', workflow))
    assert result.status == 'ok'


def test_ambiguous_sensor_burst_still_uses_assessment():
    with patch("src.graph.nodes.context_gate.audit_from_state"):
        result = ContextGateNode()(_state({"classification_confidence": 0.2}))
    assert result["needs_context_assessment"] is True


def test_paused_session_persists_location_free_activity_event(tmp_path):
    class OfflineRecordStore:
        is_available = False

    db = DatabaseService(tmp_path / "context.db")
    uid = "sparse_event_test"
    session = SessionState(status=SessionStatus.PAUSED)
    db.upsert_session(uid, session.session_id, session.model_dump(mode="json"))
    event_id = "evt_sparse_persisted"
    observed = datetime.now(timezone.utc).isoformat()

    with patch("src.services.record_store.RecordStore", OfflineRecordStore), \
         patch("src.graph.nodes.semantic_context.RecordStore", OfflineRecordStore), \
         patch("src.graph.nodes.persist.RecordStore", OfflineRecordStore):
        result = build_workflow(db).invoke({
            "uid": uid,
            "request_type": "CONTEXT_EVENT",
            "raw_request": {
                "event_id": event_id,
                "event_type": "ACTIVITY_ENTER",
                "activity": "WALKING",
                "transition": "ENTER",
                "occurred_at": observed,
                "location": None,
            },
        })

    assert result.get("error") is None
    assert result.get("needs_context_assessment") is False
    assert db.get_latest_context_event(uid)["id"] == event_id


def test_sparse_vehicle_entry_starts_generic_session_then_classifies_car():
    from src.backend.session_manager import SessionManager
    from src.models.enums import VehicleClass
    from src.models.schemas import ContextPacket, FeatureSummary

    manager = SessionManager()
    now = datetime.now(timezone.utc)
    sparse = ContextPacket(event_id="vehicle-enter", timestamp=now,
                           activity="IN_VEHICLE", transition="ENTER")
    session = manager.process_event(sparse, None)
    assert session is not None
    assert session.status == SessionStatus.ACTIVE
    assert session.vehicle_class == VehicleClass.UNKNOWN
    classified = ContextPacket(event_id="car-burst", timestamp=now,
                               activity="IN_VEHICLE", transition="ENTER",
                               feature_summary=FeatureSummary(
                                   vehicle_class_hint="CAR", classification_confidence=0.8))
    session = manager.process_event(classified, session)
    assert session.vehicle_class == VehicleClass.CAR


def test_unresolved_background_evidence_never_reduces_as_verified():
    from src.graph.nodes.session_reducer import SessionReducerNode
    node = SessionReducerNode()
    for assessment in (None, {"recommended_action": "ACCEPT", "confidence": 1.0},
                       {"recommended_action": "REJECT", "reasoning": "Evidence remains uncertain"}):
        state = {**_state({"classification_confidence": 0.2}),
                 "needs_context_assessment": True, "context_assessment": assessment}
        with patch("src.graph.nodes.session_reducer.audit_from_state"):
            result = node(state)
        assert result["session"] == state["session"]
        assert result["session"]["events"] == []
