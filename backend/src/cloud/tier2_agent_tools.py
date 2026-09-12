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


_STOP_WORDS = {
    "to", "the", "a", "an", "and", "or", "in", "at", "for", "of", "my", "me",
    "when", "i", "go", "out", "on", "remind", "about", "is", "am", "it", "this",
    "that", "please", "also", "with", "from", "while", "during", "as", "by", "if",
    "there", "here", "be", "do", "up", "down", "weekly", "daily",
}

_GENERIC_ACTION_WORDS = {
    "buy", "get", "purchase", "pick", "take", "bring", "fetch", "need", "do", "call", "check",
}

_TRAVEL_ACTIVITY_WORDS = {
    "walk", "walking", "bike", "biking", "ride", "riding", "drive", "driving",
    "motorcycle", "car", "vehicle", "run", "running", "bicycle", "foot",
}


def _stem_word(w: str) -> str:
    """Basic stemmer for common activity/task words (walking -> walk, bikes -> bike)."""
    w = w.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            return w[:-len(suffix)]
    return w


def _extract_task_tokens(text: str) -> tuple[set[str], set[str]]:
    """Extract (core_tokens, task_specific_tokens) for a reminder title."""
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    stemmed = [_stem_word(w) for w in words]
    core = {w for w in stemmed if w not in _STOP_WORDS}
    task = {w for w in core if w not in _GENERIC_ACTION_WORDS and w not in _TRAVEL_ACTIVITY_WORDS}
    return core, task


def _normalize_activity_string(act: str | None) -> str:
    """Normalize activity strings into sorted distinct uppercase terms."""
    if not act:
        return ""
    mapping = {
        "bike": "IN_VEHICLE",
        "biking": "IN_VEHICLE",
        "bicycle": "ON_BICYCLE",
        "bicycling": "ON_BICYCLE",
        "riding": "IN_VEHICLE",
        "ride": "IN_VEHICLE",
        "motorcycle": "IN_VEHICLE",
        "scooter": "IN_VEHICLE",
        "driving": "IN_VEHICLE",
        "drive": "IN_VEHICLE",
        "car": "IN_VEHICLE",
        "vehicle": "IN_VEHICLE",
        "in_vehicle": "IN_VEHICLE",
        "walking": "WALKING",
        "walk": "WALKING",
        "foot": "ON_FOOT",
        "on_foot": "ON_FOOT",
        "running": "RUNNING",
        "run": "RUNNING",
        "still": "STILL",
        "stationary": "STILL",
    }
    found = set()
    words = re.findall(r"[a-zA-Z_]+", str(act).lower())
    for w in words:
        if w in mapping:
            found.add(mapping[w])
        elif w.upper() in {"IN_VEHICLE", "ON_BICYCLE", "ON_FOOT", "RUNNING", "WALKING", "STILL"}:
            found.add(w.upper())
    return ", ".join(sorted(found))


def _are_matching_errands(
    title1: str, loc1: str | None,
    title2: str, loc2: str | None,
) -> bool:
    """Check if two reminders represent the same underlying task, errand, or intention."""
    t1 = (title1 or "").strip().lower()
    t2 = (title2 or "").strip().lower()
    if not t1 or not t2:
        return False
    if t1 == t2 or t1 in t2 or t2 in t1:
        return True

    core1, task1 = _extract_task_tokens(t1)
    core2, task2 = _extract_task_tokens(t2)

    # 1. Direct task noun/intent matching (e.g. "milk" in both, "refuel" in both, "flat" in both)
    task_common = task1.intersection(task2)
    if task_common:
        if task_common.issubset(task1) and (task_common == task1 or task_common == task2 or len(task1) <= 1 or len(task2) <= 1):
            return True
        if len(task_common) >= 2:
            return True

    # 2. Core tokens overlap (>= 2 words or single core overlap if one is very short)
    core_common = core1.intersection(core2)
    if len(core_common) >= 2:
        return True
    if len(core_common) >= 1 and (len(core1) <= 1 or len(core2) <= 1):
        return True

    # 3. Location matches and at least 1 core or task word matches
    l1 = (loc1 or "").strip().lower()
    l2 = (loc2 or "").strip().lower()
    if l1 and l2 and (l1 == l2 or l1 in l2 or l2 in l1) and (task_common or core_common):
        return True

    return False


def _resolve_location_and_coords(
    db: DatabaseService, uid: str, location_name: str | None,
    lat: float | None = None, lon: float | None = None,
) -> tuple[str | None, float | None, float | None]:
    """Resolve location name ambiguity against user's saved places and fill GPS coordinates."""
    if not location_name or not location_name.strip():
        return None, lat, lon
    loc_clean = location_name.strip()
    loc_lower = loc_clean.lower()
    resolved_lat = lat
    resolved_lon = lon
    resolved_name = loc_clean

    # If coordinates missing, check if latest GPS is available
    current_lat, current_lon = resolved_lat, resolved_lon
    if current_lat is None or current_lon is None:
        try:
            latest_gps = db.get_latest_gps(uid)
            if latest_gps and latest_gps.get("latitude"):
                current_lat = latest_gps["latitude"]
                current_lon = latest_gps["longitude"]
        except Exception:
            pass

    # Check relative current-location phrases: "here", "this gate", "gate", "current location", "this place"
    relative_keywords = (
        "here",
        "this gate",
        "the gate",
        "out of this gate",
        "out of the gate",
        "gate",
        "current location",
        "this place",
        "current spot",
        "my flat",
        "leave here",
        "leaving here",
        "when i leave",
        "when leaving",
        "outside gate",
        "from here",
    )
    is_relative_here = any(kw in loc_lower for kw in relative_keywords) or loc_lower in ("gate", "home", "flat")

    try:
        places = db.list_places(uid)
        if not places and not is_test_environment():
            try:
                from ..services.firestore_service import FirestoreService
                fs = FirestoreService()
                if fs.is_available:
                    for p in fs.get_places(uid):
                        db.create_place(uid, p)
                    places = db.list_places(uid)
            except Exception:
                pass

        # If user refers to "here" or "this gate", match against current GPS proximity to saved places
        if is_relative_here and current_lat is not None and current_lon is not None:
            from ..backend.session_manager import _haversine_m
            for p in places:
                plat = p.get("latitude")
                plon = p.get("longitude")
                if plat and plon and (plat != 0.0 or plon != 0.0):
                    d = _haversine_m(current_lat, current_lon, plat, plon)
                    if d <= (p.get("radius_m") or 150.0):
                        return p.get("name") or loc_clean, plat, plon
            return "Current Location", current_lat, current_lon

        # 1. Exact match on name, user_label/alias, or category
        for p in places:
            p_name = (p.get("name") or "").lower().strip()
            p_alias = (p.get("user_label") or p.get("alias") or "").lower().strip()
            p_cat = (p.get("category") or "").lower().strip()
            if loc_lower in (p_name, p_alias, p_cat):
                plat = p.get("latitude")
                plon = p.get("longitude")
                return p.get("name") or loc_clean, plat if resolved_lat is None else resolved_lat, plon if resolved_lon is None else resolved_lon

        # 2. Semantic synonym match (work/office, home/flat/house)
        WORK_SYNONYMS = {"work", "office", "workplace", "job"}
        HOME_SYNONYMS = {"home", "flat", "house", "apartment", "residence"}
        for p in places:
            p_name = (p.get("name") or "").lower().strip()
            p_alias = (p.get("user_label") or p.get("alias") or "").lower().strip()
            p_cat = (p.get("category") or "").lower().strip()
            p_combined = f"{p_name} {p_alias} {p_cat}"
            if loc_lower in WORK_SYNONYMS and any(w in p_combined for w in WORK_SYNONYMS):
                plat = p.get("latitude")
                plon = p.get("longitude")
                return p.get("name") or loc_clean, plat if resolved_lat is None else resolved_lat, plon if resolved_lon is None else resolved_lon
            if loc_lower in HOME_SYNONYMS and any(h in p_combined for h in HOME_SYNONYMS):
                plat = p.get("latitude")
                plon = p.get("longitude")
                return p.get("name") or loc_clean, plat if resolved_lat is None else resolved_lat, plon if resolved_lon is None else resolved_lon

        # 3. Substring or token match (e.g. "flat" matches "My Flat Valencia" or "Home")
        for p in places:
            p_name = (p.get("name") or "").lower().strip()
            p_alias = (p.get("user_label") or p.get("alias") or "").lower().strip()
            p_cat = (p.get("category") or "").lower().strip()
            if (loc_lower and loc_lower in p_name) or (p_name and p_name in loc_lower) or (p_alias and (loc_lower in p_alias or p_alias in loc_lower)):
                plat = p.get("latitude")
                plon = p.get("longitude")
                return p.get("name") or loc_clean, plat if resolved_lat is None else resolved_lat, plon if resolved_lon is None else resolved_lon
            # Token match excluding stop words
            loc_core, _ = _extract_task_tokens(loc_clean)
            p_core, _ = _extract_task_tokens(f"{p_name} {p_alias} {p_cat}")
            if loc_core and loc_core.issubset(p_core):
                plat = p.get("latitude")
                plon = p.get("longitude")
                return p.get("name") or loc_clean, plat if resolved_lat is None else resolved_lat, plon if resolved_lon is None else resolved_lon

        # If user specified a location name but has no coords, and current GPS is available, attach current GPS
        if resolved_lat is None and current_lat is not None and is_relative_here:
            resolved_lat = current_lat
            resolved_lon = current_lon

    except Exception as e:
        logger.debug("Location resolution note: %s", e)

    return resolved_name, resolved_lat, resolved_lon


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
            activity: Optional vehicle/movement trigger. If the user mentions multiple travel modes (e.g. 'walking or riding my bike'), specify them comma-separated (e.g. 'WALKING, IN_VEHICLE' or 'WALKING, ON_BICYCLE') so a single reminder fires on ANY of the modes instead of creating duplicate reminders.
            due_at: Optional ISO timestamp or relative duration (e.g. 'in 29 seconds'). Leave empty if not time-based.
            latitude: Optional GPS latitude coordinate.
            longitude: Optional GPS longitude coordinate.
        """
        try:
            parsed_due = normalize_due_at(due_at) or None
            norm_activity = _normalize_activity_string(activity) or None

            # Auto-detect relative location cues from title if location_name is omitted
            if not location_name:
                t_lower = title.lower()
                for rel_phrase in (
                    "out of this gate", "out of the gate", "this gate", "the gate",
                    "leave here", "leaving here", "when i leave", "when leaving",
                    "outside gate", "from here", "at my flat", "near home", "at home"
                ):
                    if rel_phrase in t_lower:
                        location_name = rel_phrase
                        break

            resolved_loc, res_lat, res_lon = _resolve_location_and_coords(
                db, uid, location_name, latitude, longitude
            )

            if fs.is_available and not is_test_environment():
                try:
                    for r in fs.get_reminders(uid):
                        db.create_reminder(uid, r)
                except Exception as fe:
                    logger.debug("Firestore create_reminder sync note: %s", fe)

            # Digest existing active reminders: check if an existing reminder for the same task/errand exists to consolidate
            existing_rems = db.list_reminders(uid, status="ACTIVE", limit=50)
            matching_existing = None
            for r in existing_rems:
                if _are_matching_errands(title, resolved_loc, r.get("title", ""), r.get("location_name")):
                    matching_existing = r
                    break

            if matching_existing:
                rem_id = matching_existing["id"]
                # Merge activities across both
                existing_act = matching_existing.get("activity") or ""
                combined_acts = set()
                for act_part in _normalize_activity_string(existing_act).split(","):
                    if act_part.strip():
                        combined_acts.add(act_part.strip())
                if norm_activity:
                    for act_part in norm_activity.split(","):
                        if act_part.strip():
                            combined_acts.add(act_part.strip())
                merged_activity = ", ".join(sorted(combined_acts)) if combined_acts else None

                final_lat = res_lat if res_lat is not None else matching_existing.get("latitude")
                final_lon = res_lon if res_lon is not None else matching_existing.get("longitude")
                final_loc = resolved_loc or matching_existing.get("location_name") or None

                merged_data = {
                    "title": title or matching_existing.get("title"),
                    "location_name": final_loc,
                    "activity": merged_activity,
                    "due_at": parsed_due if parsed_due is not None else matching_existing.get("due_at"),
                    "latitude": final_lat,
                    "longitude": final_lon,
                    "status": "ACTIVE",
                }
                db.update_reminder(uid, rem_id, merged_data)
                if fs.is_available and not is_test_environment():
                    fs.save_reminder(rem_id, {**merged_data, "id": rem_id, "uid": uid, "created_at": matching_existing.get("created_at")})

                # Clean up any other sibling duplicate active reminders with matching title/errand
                for other in existing_rems:
                    if other["id"] != rem_id:
                        if _are_matching_errands(title, resolved_loc, other.get("title", ""), other.get("location_name")):
                            db.delete_reminder(uid, other["id"])
                            if fs.is_available and not is_test_environment():
                                fs.delete_reminder(other["id"])

                act_summary = f" covering activities: [{merged_activity}]" if merged_activity else ""
                loc_summary = f" at {final_loc}" if final_loc else ""
                return f"Consolidated into a single intelligent reminder: '{merged_data['title']}'{loc_summary}{act_summary} (ID: {rem_id})"

            data = {
                "title": title,
                "location_name": resolved_loc,
                "activity": norm_activity,
                "due_at": parsed_due,
                "latitude": res_lat,
                "longitude": res_lon,
                "status": "ACTIVE",
            }
            res = db.create_reminder(uid, data)
            rem_id = res.get("id", "saved")
            created_at = res.get("created_at") or datetime.now(timezone.utc).isoformat()
            if fs.is_available and not is_test_environment():
                fs.save_reminder(rem_id, {**data, "id": rem_id, "uid": uid, "created_at": created_at})
            return f"Successfully created reminder: '{title}' (ID: {rem_id})"
        except Exception as e:
            return f"Error creating reminder: {e}"


    @tool
    def update_reminder(
        reminder_id: str,
        title: str = "",
        location_name: str = "",
        activity: str = "",
        due_at: str = "",
        status: str = "",
    ) -> str:
        """Update an existing reminder's conditions, title, location, activity, or status.
        Args:
            reminder_id: The ID or title of the reminder to update.
            title: Optional updated title.
            location_name: Optional updated location trigger name.
            activity: Optional updated vehicle/movement trigger (e.g. 'WALKING, IN_VEHICLE' for multiple modes).
            due_at: Optional updated ISO timestamp or relative duration.
            status: Optional updated status: 'ACTIVE', 'PAUSED', 'COMPLETED'.
        """
        try:
            target_id = reminder_id
            existing = db.get_reminder(uid, target_id)
            if not existing:
                recs = db.list_reminders(uid, limit=50)
                for r in recs:
                    if reminder_id.lower() in (str(r.get("title", "")).lower() or str(r.get("body", "")).lower()):
                        target_id = r["id"]
                        existing = r
                        break
            if not existing:
                return f"Could not find reminder matching '{reminder_id}' to update."

            patch: dict[str, Any] = {}
            if title:
                patch["title"] = title
            if location_name:
                resolved_loc, loc_lat, loc_lon = _resolve_location_and_coords(db, uid, location_name)
                patch["location_name"] = resolved_loc
                if loc_lat is not None:
                    patch["latitude"] = loc_lat
                    patch["longitude"] = loc_lon
            if activity:
                patch["activity"] = _normalize_activity_string(activity) or None
            if due_at:
                patch["due_at"] = normalize_due_at(due_at) or None
            if status:
                patch["status"] = status.upper()

            res = db.update_reminder(uid, target_id, patch)
            if fs.is_available and not is_test_environment():
                fs.save_reminder(target_id, {**existing, **patch, "id": target_id, "uid": uid})
            return f"Successfully updated reminder '{res.get('title', target_id)}' (ID: {target_id})."
        except Exception as e:
            return f"Error updating reminder: {e}"


    @tool
    def consolidate_reminders(criteria: str = "") -> str:
        """Digest and consolidate existing active reminders that match specific criteria or share similar tasks/errands into a single intelligent reminder.
        Merges multiple travel/activity triggers (e.g. WALKING and IN_VEHICLE), unified locations, and timing conditions, while removing redundant duplicate reminders.
        Args:
            criteria: Optional topic, task keywords, location, or activity to target for consolidation (e.g. 'groceries', 'walking or bike', 'flat', or '' / 'all' to digest all active reminders).
        """
        try:
            if fs.is_available and not is_test_environment():
                try:
                    for r in fs.get_reminders(uid):
                        db.create_reminder(uid, r)
                except Exception as fe:
                    logger.debug("Firestore consolidate_reminders sync note: %s", fe)

            active_rems = db.list_reminders(uid, status="ACTIVE", limit=50)
            if not active_rems:
                return "No active reminders found to consolidate."

            criteria_clean = (criteria or "").strip().lower()
            target_rems = active_rems
            if criteria_clean and criteria_clean not in ("all", "any", "*"):
                target_rems = [
                    r for r in active_rems
                    if _are_matching_errands(criteria_clean, criteria_clean, r.get("title", ""), r.get("location_name"))
                    or criteria_clean in (r.get("title", "")).lower()
                    or criteria_clean in (r.get("location_name") or "").lower()
                    or criteria_clean in (r.get("activity") or "").lower()
                ]
                if not target_rems:
                    return f"No active reminders found matching criteria '{criteria}'."

            # Group target reminders into clusters by matching errand/task/location
            clusters: list[list[dict[str, Any]]] = []
            for r in target_rems:
                placed = False
                for c in clusters:
                    lead = c[0]
                    if _are_matching_errands(r.get("title", ""), r.get("location_name"), lead.get("title", ""), lead.get("location_name")):
                        c.append(r)
                        placed = True
                        break
                if not placed:
                    clusters.append([r])

            if criteria_clean and criteria_clean not in ("all", "any", "*") and len(clusters) > 1 and len(target_rems) > 1:
                clusters = [target_rems]

            consolidated_summaries = []
            for cluster in clusters:
                if len(cluster) == 1 and not criteria_clean:
                    continue

                primary = cluster[0]
                prim_id = primary["id"]

                merged_acts = set()
                for rem in cluster:
                    for act_part in _normalize_activity_string(rem.get("activity")).split(","):
                        if act_part.strip():
                            merged_acts.add(act_part.strip())
                if criteria_clean:
                    crit_norm = _normalize_activity_string(criteria_clean)
                    if crit_norm:
                        for act_part in crit_norm.split(","):
                            if act_part.strip():
                                merged_acts.add(act_part.strip())

                merged_activity = ", ".join(sorted(merged_acts)) if merged_acts else None

                best_loc = None
                best_lat = None
                best_lon = None
                for rem in cluster:
                    loc = rem.get("location_name")
                    lat = rem.get("latitude")
                    lon = rem.get("longitude")
                    if lat is not None and lon is not None:
                        best_loc = loc or best_loc
                        best_lat = lat
                        best_lon = lon
                        break
                    elif loc and not best_loc:
                        best_loc = loc

                resolved_loc, resolved_lat, resolved_lon = _resolve_location_and_coords(
                    db, uid, best_loc, best_lat, best_lon
                )

                best_due = None
                for rem in cluster:
                    due = rem.get("due_at")
                    if due and str(due).strip():
                        best_due = str(due).strip()
                        break

                best_title = max((rem.get("title") or "" for rem in cluster), key=len) or primary.get("title")

                patch = {
                    "title": best_title,
                    "location_name": resolved_loc,
                    "latitude": resolved_lat,
                    "longitude": resolved_lon,
                    "activity": merged_activity,
                    "due_at": best_due,
                    "status": "ACTIVE",
                }
                db.update_reminder(uid, prim_id, patch)
                if fs.is_available and not is_test_environment():
                    fs.save_reminder(prim_id, {**primary, **patch, "id": prim_id, "uid": uid})

                for other in cluster[1:]:
                    other_id = other["id"]
                    db.delete_reminder(uid, other_id)
                    if fs.is_available and not is_test_environment():
                        fs.delete_reminder(other_id)

                act_str = f" [Activities: {merged_activity}]" if merged_activity else ""
                loc_str = f" (at {resolved_loc})" if resolved_loc else ""
                consolidated_summaries.append(
                    f"• Consolidated {len(cluster)} reminder(s) into '{best_title}'{loc_str}{act_str} (ID: {prim_id})"
                )

            if not consolidated_summaries:
                return "All active reminders are already unique and consolidated."

            return "Successfully digested and consolidated reminders:\n" + "\n".join(consolidated_summaries)
        except Exception as e:
            logger.error("Error consolidating reminders: %s", e)
            return f"Error consolidating reminders: {e}"


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
        """Get the user's current exact location, saved places, immediate building/landmark, and address."""
        try:
            from ..backend.session_manager import _haversine_m
            from ..services.places_client import PlacesClient
            from ..graph.nodes.tier2_agent import reverse_geocode_location

            if fs.is_available and not is_test_environment():
                try:
                    for p in fs.get_places(uid):
                        db.create_place(uid, p)
                except Exception:
                    pass

            gps = db.get_latest_gps(uid)
            if not gps or not gps.get("latitude"):
                return "No live GPS coordinates available in the current session."
            lat = gps["latitude"]
            lon = gps["longitude"]
            lines = []

            # 1. Check saved places first (highest precision intent)
            places = db.list_places(uid)
            exact_saved = None
            nearby_saved = []
            for p in places:
                plat = p.get("latitude")
                plon = p.get("longitude")
                if plat and plon and (plat != 0.0 or plon != 0.0):
                    d = _haversine_m(lat, lon, plat, plon)
                    label = p.get("user_label") or p.get("alias") or p.get("category") or "place"
                    if d <= 40.0:
                        exact_saved = f"CURRENTLY AT saved place: '{p.get('name')}' ({label}, exact location match, ~{int(d)}m)"
                    elif d <= (p.get("radius_m") or 150.0):
                        nearby_saved.append(f"At saved place '{p.get('name')}' ({label}, within compound, ~{int(d)}m away)")
                    elif d <= 1500.0:
                        nearby_saved.append(f"Near saved place '{p.get('name')}' (~{int(d)}m away)")

            if exact_saved:
                lines.append(exact_saved)
            elif nearby_saved:
                lines.append("Saved Places Proximity: " + "; ".join(nearby_saved))

            # 2. Google Places landmarks (identifying building footprint)
            try:
                client = PlacesClient()
                pois = client.search_nearby(lat, lon, radius_m=250.0, uid=uid, max_results=5)
                if pois:
                    landmarks = []
                    for p in pois:
                        cat = p.category.replace("_", " ")
                        d = int(p.distance_m)
                        if d <= 65 and any(k in cat for k in ("apartment", "building", "residential", "complex", "premise")):
                            landmarks.append(f"{p.name} (CURRENT BUILDING / PREMISE, {cat})")
                        else:
                            landmarks.append(f"{p.name} ({cat}, ~{d}m away)")
                    lines.append(f"Immediate Landmarks: {', '.join(landmarks)}")
            except Exception as pe:
                logger.debug("Google Places search error: %s", pe)

            # 3. Reverse geocoded address
            addr = reverse_geocode_location(lat, lon)
            if addr:
                lines.append(f"Area / Address: {addr}")

            lines.append(f"[Internal GPS Reference: {lat:.5f}, {lon:.5f}]")
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
        update_reminder,
        consolidate_reminders,
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
