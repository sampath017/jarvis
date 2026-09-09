"""
Tier 2 LangChain Agent Tools.

Provides callable LangChain @tool wrappers around Jarvis database CRUD operations,
allowing the Tier 2 ReAct agent to autonomously create, read, update, delete, and search
reminders, notes, tasks, and places with automatic Firestore cloud synchronization.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any
from langchain_core.tools import tool

from ..services.database import DatabaseService
from ..services.firestore_service import FirestoreService

logger = logging.getLogger(__name__)


def is_test_environment() -> bool:
    """Return True if executing inside automated unit/integration tests."""
    return "pytest" in sys.modules or os.getenv("ENVIRONMENT") == "testing"


def normalize_due_at(due_at: str) -> str:
    """Normalize relative expressions (e.g. 'in 29 seconds') into ISO 8601 UTC timestamp."""
    val = (due_at or "").strip()
    if not val:
        return ""
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    lower = val.lower()

    match = re.search(
        r'(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours|d|day|days)',
        lower,
    )
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        if unit.startswith('s'):
            return (now + timedelta(seconds=count)).isoformat()
        elif unit.startswith('m'):
            return (now + timedelta(minutes=count)).isoformat()
        elif unit.startswith('h'):
            return (now + timedelta(hours=count)).isoformat()
        elif unit.startswith('d'):
            return (now + timedelta(days=count)).isoformat()

    return val


def build_tier2_tools(db: DatabaseService, uid: str) -> list[Any]:
    """Build a list of LangChain tools bound to the authenticated user's database scope."""
    fs = FirestoreService()

    # ── Reminders ────────────────────────────────────────────────────────────

    @tool
    def create_reminder(
        title: str,
        location_name: str = "",
        activity: str = "",
        due_at: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> str:
        """Create a new context-aware reminder for the user.
        Args:
            title: The reminder text (e.g. 'Refuel at Indian Oil', 'Check tire pressure').
            location_name: Optional location trigger (e.g. 'Indian Oil', 'Home', 'Office').
            activity: Optional vehicle/movement trigger (e.g. 'IN_VEHICLE', 'WALKING').
            due_at: Optional ISO timestamp or relative duration (e.g. 'in 29 seconds').
            latitude: Optional GPS latitude coordinate.
            longitude: Optional GPS longitude coordinate.
        """
        try:
            parsed_due = normalize_due_at(due_at)
            # Auto-resolve coordinates from saved places if not explicitly passed
            if (latitude is None or longitude is None) and location_name:
                try:
                    places = db.list_places(uid)
                    loc_lower = location_name.lower().strip()
                    for p in places:
                        p_name = (p.get("name") or "").lower().strip()
                        p_alias = (p.get("alias") or "").lower().strip()
                        if loc_lower == p_name or loc_lower == p_alias or loc_lower in p_name or p_name in loc_lower:
                            latitude = p.get("latitude")
                            longitude = p.get("longitude")
                            break
                except Exception as pe:
                    logger.debug("Coordinate resolution note: %s", pe)

            data = {
                "title": title,
                "location_name": location_name,
                "activity": activity,
                "due_at": parsed_due,
                "latitude": latitude,
                "longitude": longitude,
                "status": "ACTIVE",
            }
            res = db.create_reminder(uid, data)
            rem_id = res.get("id", "saved")
            if fs.is_available and not is_test_environment():
                fs.save_reminder(rem_id, {**data, "id": rem_id, "uid": uid})
            return f"Successfully created reminder: '{title}' (ID: {rem_id})"
        except Exception as e:
            return f"Error creating reminder: {e}"


    @tool
    def list_reminders(status: str = "ACTIVE") -> str:
        """List the user's reminders.
        Args:
            status: Filter by status: 'ACTIVE', 'PAUSED', 'COMPLETED', or 'ALL'.
        """
        try:
            if fs.is_available:
                try:
                    for r in fs.get_reminders(uid):
                        db.create_reminder(uid, r)
                except Exception as fe:
                    logger.debug("Firestore list_reminders pull note: %s", fe)

            stat_arg = None if status.upper() == "ALL" else status.upper()
            records = db.list_reminders(uid, status=stat_arg, limit=20)
            if not records:
                return "No reminders found."
            lines = []
            for r in records:
                loc = f" (at {r.get('location_name')})" if r.get("location_name") else ""
                act = f" [on {r.get('activity')}]" if r.get("activity") else ""
                lines.append(f"• ID: {r.get('id')}: {r.get('title') or r.get('body', '')}{loc}{act} [{r.get('status', 'ACTIVE')}]")
            return f"Found {len(records)} reminder(s):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error listing reminders: {e}"

    @tool
    def search_reminders(query: str) -> str:
        """Search reminders matching a text query or keyword.
        Args:
            query: The keyword to search for in reminder titles or locations.
        """
        try:
            recs = db.list_reminders(uid, limit=50)
            matches = [
                r for r in recs
                if query.lower() in (r.get("title", "").lower() + " " + r.get("location_name", "").lower() + " " + r.get("body", "").lower())
            ]
            if not matches:
                return f"No reminders found matching '{query}'."
            lines = [f"• ID: {r.get('id')}: {r.get('title') or r.get('body', '')} [{r.get('status', 'ACTIVE')}]" for r in matches]
            return f"Found {len(matches)} reminder(s) matching '{query}':\n" + "\n".join(lines)
        except Exception as e:
            return f"Error searching reminders: {e}"

    @tool
    def delete_reminder(reminder_id: str) -> str:
        """Delete a reminder using its exact ID or title match.
        Args:
            reminder_id: The exact ID of the reminder, or the title of the reminder to delete.
        """
        try:
            if fs.is_available and not is_test_environment():
                fs.delete_reminder(reminder_id)
            ok = db.delete_reminder(uid, reminder_id)
            if ok:
                return f"Successfully deleted reminder (ID: {reminder_id})."
            recs = db.list_reminders(uid, limit=50)
            for r in recs:
                if reminder_id.lower() in (str(r.get("title", "")).lower() or str(r.get("body", "")).lower()):
                    db.delete_reminder(uid, r["id"])
                    if fs.is_available and not is_test_environment():
                        fs.delete_reminder(r["id"])
                    return f"Successfully deleted reminder '{r.get('title')}' (ID: {r['id']})."
            if fs.is_available and not is_test_environment():
                for r in fs.get_reminders(uid):
                    if reminder_id.lower() in (str(r.get("title", "")).lower() or str(r.get("body", "")).lower()):
                        fs.delete_reminder(r["id"])
                        return f"Successfully deleted reminder '{r.get('title')}' (ID: {r['id']})."
            return f"Could not find reminder matching '{reminder_id}' to delete."
        except Exception as e:
            return f"Error deleting reminder: {e}"

    @tool
    def delete_all_reminders() -> str:
        """Delete ALL reminders for the user."""
        try:
            if fs.is_available and not is_test_environment():
                fs.delete_all_reminders(uid)
            for r in db.list_reminders(uid, limit=100):
                db.delete_reminder(uid, r["id"])
            return "Successfully deleted all reminders."
        except Exception as e:
            return f"Error deleting all reminders: {e}"

    # ── Notes ────────────────────────────────────────────────────────────────

    @tool
    def create_note(text: str, title: str = "", place: str = "") -> str:
        """Create a new note or trip log for the user.
        Args:
            text: The content of the note (e.g. 'Odometer reading 4,285 km', 'Checked chain tension').
            title: Optional title for the note.
            place: Optional place where the note was recorded.
        """
        try:
            data = {"text": text, "content": text, "title": title or "Note", "place": place}
            res = db.create_note(uid, data)
            n_id = res.get("id", "saved")
            if fs.is_available:
                fs.save_note(n_id, {**data, "id": n_id, "uid": uid})
            return f"Successfully created note: '{text}' (ID: {n_id})"
        except Exception as e:
            return f"Error creating note: {e}"

    @tool
    def list_notes(limit: int = 10) -> str:
        """List the user's recent notes.
        Args:
            limit: Maximum number of notes to return.
        """
        try:
            if fs.is_available:
                try:
                    for n in fs.get_notes(uid):
                        db.create_note(uid, n)
                except Exception as fe:
                    logger.debug("Firestore list_notes pull note: %s", fe)

            records = db.list_notes(uid, limit=limit)
            if not records:
                return "No notes found."
            lines = [f"• ID {n.get('id')}: {n.get('content') or n.get('text', '')}" for n in records]
            return f"Found {len(records)} note(s):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error listing notes: {e}"

    @tool
    def search_notes(query: str) -> str:
        """Search notes matching a text query or keyword.
        Args:
            query: The keyword to search for in note content or title.
        """
        try:
            recs = db.list_notes(uid, limit=50)
            matches = [
                n for n in recs
                if query.lower() in (str(n.get("text", "")).lower() + " " + str(n.get("title", "")).lower() + " " + str(n.get("content", "")).lower())
            ]
            if not matches:
                return f"No notes found matching '{query}'."
            lines = [f"• ID {n.get('id')}: {n.get('content') or n.get('text', '')}" for n in matches]
            return f"Found {len(matches)} note(s) matching '{query}':\n" + "\n".join(lines)
        except Exception as e:
            return f"Error searching notes: {e}"

    @tool
    def delete_note(note_id: str) -> str:
        """Delete a note using its ID or partial content match.
        Args:
            note_id: The ID of the note to delete, or text snippet.
        """
        try:
            if fs.is_available and not is_test_environment():
                fs.delete_note(note_id)
            ok = db.delete_note(uid, note_id)
            if ok:
                return f"Successfully deleted note (ID: {note_id})."
            recs = db.list_notes(uid, limit=50)
            for n in recs:
                if note_id.lower() in str(n.get("text", "")).lower() or note_id.lower() in str(n.get("title", "")).lower() or note_id.lower() in str(n.get("content", "")).lower():
                    db.delete_note(uid, n["id"])
                    if fs.is_available and not is_test_environment():
                        fs.delete_note(n["id"])
                    return f"Successfully deleted note: '{n.get('content') or n.get('text')}' (ID: {n['id']})."
            if fs.is_available and not is_test_environment():
                for n in fs.get_notes(uid):
                    if note_id.lower() in str(n.get("text", "")).lower() or note_id.lower() in str(n.get("title", "")).lower() or note_id.lower() in str(n.get("content", "")).lower():
                        fs.delete_note(n["id"])
                        return f"Successfully deleted note: '{n.get('content') or n.get('text')}' (ID: {n['id']})."
            return f"Could not find note matching '{note_id}' to delete."
        except Exception as e:
            return f"Error deleting note: {e}"

    @tool
    def delete_all_notes() -> str:
        """Delete ALL notes for the user."""
        try:
            if fs.is_available and not is_test_environment():
                fs.delete_all_notes(uid)
            for n in db.list_notes(uid, limit=100):
                db.delete_note(uid, n["id"])
            return "Successfully deleted all notes."
        except Exception as e:
            return f"Error deleting all notes: {e}"

    # ── Tasks ────────────────────────────────────────────────────────────────

    @tool
    def create_task(title: str, priority: str = "MEDIUM", due_date: str = "") -> str:
        """Create a new task or action item.
        Args:
            title: Title of the task (e.g. 'Order chain lube', 'Service Hunter 350').
            priority: Priority level: 'LOW', 'MEDIUM', or 'HIGH'.
            due_date: Optional due date string.
        """
        try:
            data = {
                "title": title,
                "description": f"Priority: {priority.upper()}",
                "priority": priority.upper(),
                "due_date": due_date,
                "status": "PENDING",
            }
            res = db.create_task(uid, data)
            return f"Successfully created task: '{title}' (ID: {res.get('id', 'saved')})"
        except Exception as e:
            return f"Error creating task: {e}"

    @tool
    def list_tasks() -> str:
        """List all pending and active tasks."""
        try:
            records = db.list_tasks(uid, limit=20)
            if not records:
                return "No tasks found."
            lines = []
            for t in records:
                desc = str(t.get("description", "")).upper()
                raw_prio = t.get("priority")
                prio = str(raw_prio).upper() if raw_prio else ("HIGH" if "HIGH" in desc else "LOW" if "LOW" in desc else "MED")
                lines.append(f"• ID: {t.get('id')}: {t.get('title')} [{prio}] - {t.get('status', 'PENDING')}")
            return f"Found {len(records)} task(s):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error listing tasks: {e}"

    @tool
    def update_task(task_id: str, title: str = "", priority: str = "", new_status: str = "") -> str:
        """Update a task's title, priority, or status.
        Args:
            task_id: The ID of the task to update.
            title: New task title.
            priority: New priority ('LOW', 'MEDIUM', 'HIGH').
            new_status: New status ('PENDING', 'COMPLETED', 'CANCELLED').
        """
        try:
            updates: dict[str, Any] = {}
            if title:
                updates["title"] = title
            if new_status:
                updates["status"] = new_status.upper()
            if priority:
                updates["priority"] = priority.upper()
            res = db.update_task(uid, task_id, updates)
            if res:
                return f"Successfully updated task {task_id}."
            recs = db.list_tasks(uid, limit=50)
            for t in recs:
                if task_id.lower() in t.get("title", "").lower():
                    db.update_task(uid, t["id"], updates)
                    return f"Successfully updated task '{t.get('title')}' (ID: {t['id']})."
            return f"Task {task_id} not found."
        except Exception as e:
            return f"Error updating task: {e}"

    @tool
    def update_task_status(task_id: str, new_status: str) -> str:
        """Update a task's status (e.g. 'COMPLETED', 'PENDING').
        Args:
            task_id: The ID or title of the task.
            new_status: 'COMPLETED' or 'PENDING'.
        """
        return update_task.invoke({"task_id": task_id, "new_status": new_status})

    @tool
    def delete_task(task_id: str) -> str:
        """Delete a task using its ID or title match.
        Args:
            task_id: The ID or title of the task to delete.
        """
        try:
            ok = db.delete_task(uid, task_id)
            if ok:
                return f"Successfully deleted task (ID: {task_id})."
            recs = db.list_tasks(uid, limit=50)
            for t in recs:
                if task_id.lower() in t.get("title", "").lower():
                    db.delete_task(uid, t["id"])
                    return f"Successfully deleted task '{t.get('title')}' (ID: {t['id']})."
            return f"Could not find task matching '{task_id}' to delete."
        except Exception as e:
            return f"Error deleting task: {e}"

    # ── Places ───────────────────────────────────────────────────────────────

    @tool
    def save_place(name: str, category: str = "custom", latitude: float = 0.0, longitude: float = 0.0) -> str:
        """Save a new place or geofence (e.g. 'Home', 'Gym', 'Royal Enfield Service').
        Args:
            name: Place name.
            category: Place category (e.g. 'home', 'work', 'gym', 'service').
            latitude: Latitude coordinate.
            longitude: Longitude coordinate.
        """
        try:
            data = {"name": name, "category": category, "latitude": latitude, "longitude": longitude}
            res = db.create_place(uid, data)
            p_id = res.get("id", "saved")
            if fs.is_available:
                fs.save_place(p_id, {**data, "id": p_id, "uid": uid})
            return f"Successfully saved place: '{name}' (ID: {p_id})"
        except Exception as e:
            return f"Error saving place: {e}"

    @tool
    def list_saved_places() -> str:
        """List the user's saved places and geofences."""
        try:
            if fs.is_available:
                try:
                    for p in fs.get_places(uid):
                        db.create_place(uid, p)
                except Exception as fe:
                    logger.debug("Firestore list_saved_places pull note: %s", fe)

            records = db.list_places(uid)
            if not records:
                return "No saved places found."
            lines = [f"• ID: {p.get('id')}: {p.get('name')} ({p.get('category', 'place')}) - Lat: {p.get('latitude')}, Lon: {p.get('longitude')}" for p in records]
            return f"Found {len(records)} saved place(s):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error listing places: {e}"

    @tool
    def delete_place(place_id: str) -> str:
        """Delete a saved place by ID or name match.
        Args:
            place_id: The ID or name of the place to delete.
        """
        try:
            ok = db.delete_place(uid, place_id)
            if ok:
                if fs.is_available:
                    fs.delete_place(place_id)
                return f"Successfully deleted place (ID: {place_id})."
            recs = db.list_places(uid)
            for p in recs:
                if place_id.lower() in p.get("name", "").lower():
                    db.delete_place(uid, p["id"])
                    if fs.is_available:
                        fs.delete_place(p["id"])
                    return f"Successfully deleted place '{p.get('name')}' (ID: {p['id']})."
            return f"Could not find place matching '{place_id}' to delete."
        except Exception as e:
            return f"Error deleting place: {e}"

    @tool
    def search_nearby_places(query: str = "", radius_m: float = 250.0) -> str:
        """Search nearby places, landmarks, buildings, and establishments using Google Places API.
        Args:
            query: Optional place keyword or category (e.g. 'apartments', 'cafe', 'restaurant', 'store').
            radius_m: Search radius around the user in meters (default 250m).
        """
        try:
            from ..services.places_client import PlacesClient
            gps = db.get_latest_gps(uid)
            if not gps or not gps.get("latitude"):
                return "Cannot search nearby places: no recent location fix available."
            lat = gps["latitude"]
            lon = gps["longitude"]
            client = PlacesClient()
            pois = client.search_nearby(lat, lon, radius_m=radius_m, uid=uid, max_results=8)
            if not pois:
                return f"No landmarks or places found within {int(radius_m)}m."
            lines = []
            for p in pois:
                cat = p.category.replace("_", " ")
                lines.append(f"• {p.name} ({cat}) - ~{int(p.distance_m)}m away")
            return f"Nearby places from Google Places (within {int(radius_m)}m):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error searching Google Places: {e}"

    @tool
    def get_current_location() -> str:
        """Get the user's current location, immediate landmarks (via Google Places), address, and saved places."""
        try:
            from ..backend.session_manager import _haversine_m
            from ..services.places_client import PlacesClient
            from ..graph.nodes.tier2_agent import reverse_geocode_location

            gps = db.get_latest_gps(uid)
            if not gps or not gps.get("latitude"):
                return "No live GPS coordinates available in the current session."
            lat = gps["latitude"]
            lon = gps["longitude"]
            lines = []

            # 1. Google Places landmarks
            try:
                client = PlacesClient()
                pois = client.search_nearby(lat, lon, radius_m=250.0, uid=uid, max_results=4)
                if pois:
                    landmarks = [f"{p.name} (~{int(p.distance_m)}m)" for p in pois]
                    lines.append(f"Immediate Landmarks (Google Places): {', '.join(landmarks)}")
            except Exception as pe:
                logger.debug("Google Places search error: %s", pe)

            # 2. Reverse geocoded address
            addr = reverse_geocode_location(lat, lon)
            if addr:
                lines.append(f"Area / Address: {addr}")

            # 3. Check saved places
            places = db.list_places(uid)
            nearby = []
            for p in places:
                plat = p.get("latitude")
                plon = p.get("longitude")
                if plat and plon:
                    d = _haversine_m(lat, lon, plat, plon)
                    if d <= (p.get("radius_m") or 150):
                        nearby.append(f"At saved place '{p.get('name')}' ({p.get('category', 'place')}, ~{int(d)}m away)")
                    elif d <= 1500:
                        nearby.append(f"Near saved place '{p.get('name')}' (~{int(d)}m away)")
            if nearby:
                lines.append("Saved Places Proximity: " + "; ".join(nearby))

            return "\n".join(lines) if lines else "Location acquired, but no named landmarks found."
        except Exception as e:
            return f"Error reading location: {e}"

    @tool
    def respond_to_user(
        message: str,
        intent: str = "general",
        resolved_place: str = "",
    ) -> str:
        """Deliver the final structured response to the user. Use this tool to complete the interaction cleanly.

        Args:
            message: Clean, natural human response to the user. Plain text without unrendered markdown asterisks, raw coordinates, or broken symbols.
            intent: Primary recognized intent ('location_query', 'create_reminder', 'delete_reminder', 'list_reminders', 'create_note', 'save_place', 'general').
            resolved_place: Human-readable building or place name if location was asked or referenced.
        """
        return message

    return [
        create_reminder,
        list_reminders,
        search_reminders,
        delete_reminder,
        delete_all_reminders,
        create_note,
        list_notes,
        search_notes,
        delete_note,
        delete_all_notes,
        create_task,
        list_tasks,
        update_task,
        update_task_status,
        delete_task,
        save_place,
        list_saved_places,
        delete_place,
        get_current_location,
        search_nearby_places,
        respond_to_user,
    ]
