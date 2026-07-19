"""
Load Context node — scoped Firestore retrieval.

Class-based node implementation for loading context from Firestore.
"""

from __future__ import annotations

import logging
from ..state import JarvisState
from ...services.firestore_client import FirestoreService

logger = logging.getLogger(__name__)


class LoadContextNode:
    """Class-based node handler for scoped Firestore context retrieval."""

    def __init__(self, firestore_service: FirestoreService | None = None) -> None:
        self.firestore_service = firestore_service or FirestoreService()

    def __call__(self, state: JarvisState) -> dict:
        """Load scoped context from Firestore for the verified user."""
        uid = state.get("uid", "")
        thread_id = state.get("thread_id")

        if not uid:
            return {"error": "No authenticated user"}

        fs = self.firestore_service

        try:
            context = fs.load_scoped_context(
                uid=uid,
                thread_id=thread_id,
            )

            # Retrieve the latest context event with a valid GPS reading
            latest_gps = None
            try:
                events = fs.list_documents(uid, "contextEvents", limit=20)
                if events:
                    events_sorted = sorted(
                        [e for e in events if e.get("timestamp")],
                        key=lambda x: x["timestamp"],
                        reverse=True
                    )
                    for event in events_sorted:
                        if event.get("gps") and event["gps"].get("latitude") is not None:
                            latest_gps = event["gps"]
                            break
            except Exception as e:
                logger.warning("Failed to fetch latest context event for location: %s", e)

            # Merge latest GPS and nearby POIs into the context packet if not present
            packet = state.get("context_packet", {})
            if latest_gps and packet:
                if not packet.get("gps"):
                    packet["gps"] = latest_gps
                
                # Enrich with nearby POIs if they aren't already set
                if not packet.get("nearby_pois"):
                    try:
                        from ...services.places_client import PlacesClient
                        client = PlacesClient()
                        pois = client.search_nearby(
                            latitude=latest_gps["latitude"],
                            longitude=latest_gps["longitude"],
                            uid=uid
                        )
                        if pois:
                            packet["nearby_pois"] = [p.model_dump() for p in pois]
                    except Exception as pe:
                        logger.warning("Failed to search nearby POIs in load_context: %s", pe)

            return {
                "session": context.get("session"),
                "tasks": context.get("tasks", []),
                "messages": context.get("messages", []),
                "preferences": context.get("preferences", []),
                "context_packet": packet,
            }

        except Exception as e:
            return {
                "session": None,
                "tasks": [],
                "messages": [],
                "preferences": [],
                "error": f"Failed to load context: {e}",
            }


# Callable instance for graph composition
load_context = LoadContextNode()
