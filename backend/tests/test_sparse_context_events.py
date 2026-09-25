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


def test_activity_transition_without_location_does_not_require_tier1():
    with patch("src.graph.nodes.context_gate.audit_from_state"):
        result = ContextGateNode()(_state())
    assert result == {"conflicts": [], "needs_tier1": False}


def test_ambiguous_sensor_burst_still_uses_tier1():
    with patch("src.graph.nodes.context_gate.audit_from_state"):
        result = ContextGateNode()(_state({"classification_confidence": 0.2}))
    assert result["needs_tier1"] is True


def test_paused_session_persists_location_free_activity_event(tmp_path):
    class OfflineFirestore:
        is_available = False

    db = DatabaseService(tmp_path / "context.db")
    uid = "sparse_event_test"
    session = SessionState(status=SessionStatus.PAUSED)
    db.upsert_session(uid, session.session_id, session.model_dump(mode="json"))
    event_id = "evt_sparse_persisted"
    observed = datetime.now(timezone.utc).isoformat()

    with patch("src.services.firestore_service.FirestoreService", OfflineFirestore), \
         patch("src.graph.nodes.semantic_context.FirestoreService", OfflineFirestore), \
         patch("src.graph.nodes.persist.FirestoreService", OfflineFirestore):
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
    assert result.get("needs_tier1") is False
    assert db.get_latest_context_event(uid)["id"] == event_id
