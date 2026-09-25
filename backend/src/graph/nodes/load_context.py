"""
Load Context node — scoped local database retrieval.

Class-based node implementation for loading context from SQLite.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from ..state import JarvisState
from ...services.database import DatabaseService
from ...backend.audit_log import audit_from_state

logger = logging.getLogger(__name__)


class LoadContextNode:
    """Class-based node handler for scoped local database context retrieval."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()

    def __call__(self, state: JarvisState) -> dict:
        """Load scoped context from local database for the verified user."""
        uid = state.get("uid", "")
        thread_id = state.get("thread_id") or state.get("raw_request", {}).get("thread_id")
        audit = audit_from_state(state, self.db)

        if not uid:
            audit.log(
                node_name="load_context",
                action="no_authenticated_user",
                category="CONTEXT",
                execution_result="error",
                error_detail="No authenticated user",
            )
            return {"error": "No authenticated user"}

        try:
            if state.get('request_type') == 'USER_COMMAND':
                raw = state.get('raw_request') or {}
                # The conversational agent selects the relevant tool first. File
                # questions must not trigger GPS, Places, or mobility hydration.
                messages = raw.get('history') or (self.db.get_recent_messages(uid, thread_id, limit=8) if thread_id else [])
                return {'thread_id': thread_id, 'messages': messages,
                        'context_scope': 'on_demand', 'cloud_context_loaded': True,
                        'context_packet': {}, 'session': None, 'tasks': [],
                        'reminders': [], 'notes': [], 'preferences': [],
                        'context_memory': [], 'context_history': None, 'semantic_contexts': []}
            context = self.db.load_scoped_context(uid=uid, thread_id=thread_id)
            context_memory = []
            semantic_contexts = []
            cloud_context_loaded = False
            context_history = None

            # A Cloud Run request can land on any instance.  Prefer the
            # uid-scoped Firestore session so journey context survives an
            # instance recycle; SQLite remains an offline/local fallback.
            try:
                from ...services.firestore_service import FirestoreService
                from ...cloud.tier2_agent_tools import is_test_environment
                fs = FirestoreService()
                if is_test_environment():
                    fs._db = None
                if fs.is_available:
                    reads = {
                        "session": lambda: fs.get_active_mobility_session(uid),
                        "reminders": lambda: fs.get_reminders(uid),
                        "places": lambda: fs.get_places(uid),
                    }
                    if state.get("request_type") == "USER_COMMAND":
                        reads.update({
                            "memory": lambda: fs.get_context_memory(uid, limit=20),
                            "semantic": lambda: fs.get_semantic_contexts(uid),
                        })
                        from ...backend.context_history import prefetch_history_window, build_timeline
                        window = prefetch_history_window((state.get("raw_request") or {}).get("text", ""))
                        if window:
                            def read_history():
                                from ...backend.activity_sessions import enriched_history
                                history, _ = enriched_history(fs, uid, *window)
                                return history
                            reads["history"] = read_history
                    results = {}
                    # Only independent remote reads run concurrently. SQLite
                    # hydration happens afterwards, on the requesting thread.
                    with ThreadPoolExecutor(max_workers=len(reads)) as pool:
                        pending = {name: pool.submit(read) for name, read in reads.items()}
                        for name, future in pending.items():
                            try:
                                results[name] = future.result()
                            except Exception as exc:
                                logger.info("Optional cloud %s read skipped: %s", name, exc)
                    if results.get("session"):
                        context["session"] = results["session"]
                    context_memory = results.get("memory") or []
                    semantic_contexts = results.get("semantic") or []
                    context_history = results.get("history")
                    for reminder in results.get("reminders") or []:
                        self.db.create_reminder(uid, reminder)
                    for place in results.get("places") or []:
                        self.db.create_place(uid, place)
                    context["reminders"] = self.db.list_reminders(uid, status="ACTIVE", limit=15)
                    cloud_context_loaded = True
            except Exception as cloud_err:
                logger.info("Optional Firestore session hydration skipped: %s", cloud_err)

            # Retrieve the latest GPS reading from context events
            latest_gps = None
            try:
                latest_gps = self.db.get_latest_gps(uid)
                if latest_gps:
                    observed = datetime.fromisoformat(str(latest_gps.get("observed_at", "")).replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                    if not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 300:
                        latest_gps = None
            except Exception as e:
                latest_gps = None
                logger.info("Optional latest GPS fetch skipped: %s", e)

            # Merge latest GPS and nearby POIs into the context packet
            packet = dict(state.get("context_packet") or {})
            raw_req = state.get("raw_request") or {}

            gps_info = packet.get("gps")
            if not gps_info:
                if raw_req.get("latitude") is not None and raw_req.get("longitude") is not None:
                    gps_info = {
                        "latitude": raw_req["latitude"],
                        "longitude": raw_req["longitude"],
                        "accuracy_m": 10.0,
                    }
                    packet["gps"] = gps_info
                elif latest_gps and state.get("request_type") == "USER_COMMAND":
                    gps_info = latest_gps
                    packet["gps"] = latest_gps

            if gps_info:
                from ...services.places_client import PlacesClient
                from .tier2_agent import reverse_geocode_location
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    nearby = None
                    if not packet.get("nearby_pois"):
                        nearby = pool.submit(PlacesClient().search_nearby,
                            latitude=gps_info["latitude"], longitude=gps_info["longitude"],
                            radius_m=250.0, uid=uid, max_results=5)
                    address = None
                    if state.get("request_type") == "USER_COMMAND":
                        address = pool.submit(reverse_geocode_location,
                            gps_info["latitude"], gps_info["longitude"])
                    for name, future in (("nearby_pois", nearby), ("resolved_address", address)):
                        if future is None:
                            continue
                        try:
                            value = future.result()
                            packet[name] = [p.model_dump() for p in value] if name == "nearby_pois" else value
                        except Exception as exc:
                            logger.info("Optional %s enrichment skipped: %s", name, exc)
                # Empty results count as completed lookups, preventing a second
                # Places request and geocode retry during prompt construction.
                packet["location_enrichment_loaded"] = True
                logger.info("Location enrichment latency_ms=%.1f", (time.perf_counter() - started) * 1000)

            # Audit: log context loaded
            session = context.get("session")
            gps = packet.get("gps") or latest_gps or {}
            audit.log(
                node_name="load_context",
                action="context_loaded",
                category="CONTEXT",
                event_id=state.get("event_id", ""),
                input_summary={
                    "uid": uid,
                    "thread_id": thread_id,
                },
                output_summary={
                    "session_status": session.get("status") if session else None,
                    "session_id": session.get("session_id") if session else None,
                    "task_count": len(context.get("tasks", [])),
                    "message_count": len(context.get("messages", [])),
                    "preference_count": len(context.get("preferences", [])),
                    "has_gps": bool(gps),
                    "nearby_poi_count": len(packet.get("nearby_pois", [])),
                },
                gps_lat=gps.get("latitude") if isinstance(gps, dict) else None,
                gps_lon=gps.get("longitude") if isinstance(gps, dict) else None,
            )

            client_history = state.get("raw_request", {}).get("history", [])
            messages = client_history if client_history else context.get("messages", [])

            return {
                "thread_id": thread_id,
                "session": context.get("session"),
                "tasks": context.get("tasks", []),
                "reminders": context.get("reminders", []),
                "notes": context.get("notes", []),
                "messages": messages,
                "preferences": context.get("preferences", []),
                "context_packet": packet,
                "context_memory": context_memory,
                "cloud_context_loaded": cloud_context_loaded,
                "context_history": context_history,
                "semantic_contexts": semantic_contexts,
            }

        except Exception as e:
            logger.critical("Failed to load context: %s", e, exc_info=True)
            audit.log(
                node_name="load_context",
                action="context_load_failed",
                category="CONTEXT",
                event_id=state.get("event_id", ""),
                execution_result="error",
                error_detail=str(e),
            )
            return {
                "session": None,
                "tasks": [],
                "messages": [],
                "preferences": [],
                "error": f"Failed to load context: {e}",
            }


# Callable instance for graph composition
load_context = LoadContextNode()
