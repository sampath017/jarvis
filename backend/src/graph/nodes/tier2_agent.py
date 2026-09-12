"""
Tier 2 Agent Node — Autonomous LangGraph ReAct Agent.

Executes multi-turn reasoning loops with allow-listed tools, allowing the agent
to read context, invoke tools, inspect observations via ToolMessages, and formulate complete responses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...cloud.tier2_agent_tools import build_tier2_tools
from ...services.database import DatabaseService
from ...backend.audit_log import audit_from_state
from ...backend.session_manager import _haversine_m
from ...settings import (
    AGENT_MAX_ITERATIONS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL_TIER2,
    OPENROUTER_TEMPERATURE,
)
from ..state import JarvisState

logger = logging.getLogger(__name__)

_geocode_cache: dict[tuple[float, float], str] = {}


def reverse_geocode_location(lat: float, lon: float) -> str:
    """Reverse geocode coordinates to a human-readable area/address using Nominatim."""
    key = (round(lat, 3), round(lon, 3))
    if key in _geocode_cache:
        return _geocode_cache[key]
    try:
        import httpx
        headers = {"User-Agent": "JarvisContextAgent/1.0"}
        res = httpx.get(
            f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}",
            headers=headers,
            timeout=3.0,
        )
        if res.status_code == 200:
            addr = res.json().get("display_name", "")
            if addr:
                _geocode_cache[key] = addr
                return addr
    except Exception as e:
        logger.debug("Reverse geocoding error: %s", e)
    return ""

SYSTEM_PROMPT_TIER2 = """You are Jarvis, a context-aware personal assistant. You're talking directly
to the user — be natural, warm, and brief, the way a capable assistant would
be in conversation, not a chatbot reading out menu options.

TOOLS
You have CRUD tools for reminders, notes, tasks, and saved places (create,
list, update, delete, search — as available per tool). Use the ReAct pattern:

1. If you need information or need to take an action, call the appropriate
   tool.
2. Always read the tool's actual result before responding. Never tell the
   user "let me check on that" and stop — once a tool returns, use its real
   data to give a complete, specific answer in the same turn.
3. Be efficient with tool calls, but don't cut a genuinely multi-step request
   short — chain list -> create -> confirm calls as needed to fully complete
   what was asked.
4. Confirm before any destructive action (deleting a reminder, note, or task)
   if it's ambiguous which item the user means — don't guess and delete.
5. If resolved context from the Tier 1 Context Agent is available (place,
   activity), use it naturally where relevant — e.g. "since you're at the
   gym" — but never fabricate context you weren't actually given.
6. Keep responses short. This is a voice/chat assistant a person is talking
   to on the move, not a report.
7. Multi-Turn Context: Maintain dialogue continuity across conversation turns.
   When the user refers to previous items using pronouns or follow-ups (e.g.
   "that", "it", "them", "the reminder I just set", "change it to tomorrow"),
   resolve them using the preceding conversation turns in the chat history.
8. Time & Reminders: When creating reminders with a target time or duration
   (e.g., 'in 29 seconds', 'in 15 minutes', 'tomorrow at 9am'), supply `due_at`
   as an ISO-8601 UTC timestamp calculated from the current time provided in context,
   or pass a relative duration string like 'in 29 seconds'.
9. Chat History Protection: You do NOT have the ability or permission to delete
   chat conversations or chat history. If the user asks to delete chats, chat history,
   and must be managed directly by them in the mobile app UI drawer.
10. Location Awareness, Queries & Landmarks:
    - You are deeply location-aware across all user questions, queries, and reminder creations.
    - When the user asks questions referring to 'here', 'around me', 'nearby', 'this area', or asks 'where am I' / 'what is my location':
      - If the user is at or inside a saved place (e.g. Home, Creations Valencia, Siri Campus TCS), ALWAYS state clearly that they are at their saved place (e.g. "You are at Home at Creations Valencia in Navallur")!
      - Recognize physical building footprints: if an apartment complex, residential building, or workplace is marked "CURRENT BUILDING / PREMISE" or within ~65m, the user is physically INSIDE that building/complex, NOT "50m away". Never tell someone their own building is 50m away when they are inside it.
      - Describe their location using natural real-world place names: building name, neighbourhood, and nearby landmarks.
      - If asked questions about nearby places ('what restaurants are near here', 'is there a pharmacy around me'), use the current location or call `search_nearby_places`.
    - In Reminder Creation:
      - When the user gives a reminder mentioning 'here', 'this gate', 'out of this gate', 'when I leave here', 'my flat', or 'this place', link the reminder to the user's current saved place or current GPS coordinates.
      - Explicitly acknowledge the location in your response (e.g. "I'll remind you to buy eggs when you leave Creations Valencia").
    - CRITICAL: NEVER output raw latitude/longitude coordinates to the user unless they specifically ask for 'coordinates' or 'raw GPS'. Always communicate in natural human terms with real place names, building names, landmarks, and neighbourhood areas.
11. Clean Formatting & Complete Replies:
    - Keep chat replies concise, natural, and complete.
    - Avoid unnecessary markdown symbols, unrendered hashes, or isolated asterisks like `**Home**`.
    - Always conclude your thoughts cleanly so replies are complete and unambiguous.
12. Structured Output Delivery:
    - You have the `respond_to_user` tool to deliver your final response with structured fields:
      - `message`: Clean, friendly conversational message without raw markdown asterisks or numerical coordinates.
      - `intent`: Recognized user intent ('location_query', 'create_reminder', 'delete_reminder', 'list_reminders', 'create_note', 'save_place', 'general').
      - `resolved_place`: Specific landmark or place name if location was referenced.
    - Use `respond_to_user` to provide your final answer cleanly.
13. Reminder Consolidation & Single Intelligent Reminder:
    - Active reminders are provided in context under "Existing Active Reminders".
    - When a user asks to add, refine, or update a reminder (e.g. adding conditions like "walking or riding my bike", changing location, or altering time), DO NOT create multiple separate reminders for the same task or errand.
    - Digest all existing reminders and consolidate into a SINGLE intelligent reminder covering all possible criteria.
    - If the user specifies multiple travel modes (e.g. walking or riding), supply a comma-separated activity string (e.g. `activity='WALKING, IN_VEHICLE'`).
    - Resolve any location ambiguity: if the user mentions a location (e.g. 'my flat', 'home', 'Valencia', 'this gate'), match it with saved places or nearby landmarks and attach the proper coordinates.
    - Use `create_reminder` (which will automatically digest and consolidate with existing matching reminders), `update_reminder`, or `consolidate_reminders`.
    - Always ensure only ONE intelligent reminder exists per underlying intention or errand, and confirm to the user that a single unified reminder covers all their conditions."""


class Tier2AgentNode:
    """Class-based node handler for the Tier 2 ReAct agent."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()
        self.llm = ChatOpenAI(
            model=OPENROUTER_MODEL_TIER2,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            temperature=OPENROUTER_TEMPERATURE,
            max_retries=2,
            request_timeout=35.0,
        )

    def __call__(self, state: JarvisState) -> dict[str, Any]:
        uid = state.get("uid", "")
        tools = build_tier2_tools(self.db, uid)
        llm_with_tools = self.llm.bind_tools(tools)

        step_count = state.get("agent_step_count", 0) + 1
        agent_messages = list(state.get("agent_messages", []))
        audit = audit_from_state(state, self.db)
        event_id = state.get("event_id", "")

        # Initial turn setup
        if not agent_messages:
            user_prompt = self._build_user_prompt(state)
            agent_messages = [SystemMessage(content=SYSTEM_PROMPT_TIER2)]

            # Extract prior conversation turns from client payload or loaded DB context
            raw_history = state.get("raw_request", {}).get("history", [])
            history_list = raw_history or state.get("messages", [])

            # Format prior messages into conversation history (up to last 8 turns)
            for item in history_list[-8:]:
                role = str(item.get("role", "")).lower()
                content = item.get("content") or item.get("text") or ""
                if not content or not isinstance(content, str):
                    continue
                content = content.strip()
                if not content:
                    continue
                if role in ("user", "human"):
                    agent_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai", "bot"):
                    agent_messages.append(AIMessage(content=content))

            # Append current turn user prompt with context grounding
            agent_messages.append(HumanMessage(content=user_prompt))

        # Circuit breaker: stop runaway if max iterations reached
        if step_count > AGENT_MAX_ITERATIONS:
            logger.warning("Tier 2 Agent step limit reached (%d)", AGENT_MAX_ITERATIONS)
            fallback_msg = "I've completed the requested operations."
            return {
                "user_response": fallback_msg,
                "agent_step_count": step_count,
            }

        try:
            ai_msg: AIMessage = llm_with_tools.invoke(agent_messages)  # type: ignore[assignment]
        except Exception as e:
            logger.error("Tier 2 Agent invocation error: %s", e, exc_info=True)
            # Fallback without bound tools if provider errors on schema
            ai_msg = self.llm.invoke(agent_messages)  # type: ignore[assignment]

        raw_tool_calls = list(getattr(ai_msg, "tool_calls", []))

        # Check if the model delivered a structured response via respond_to_user tool
        structured_call = None
        action_tool_calls = []
        for tc in raw_tool_calls:
            if tc.get("name") == "respond_to_user":
                structured_call = tc
            else:
                action_tool_calls.append(tc)

        res_dict: dict[str, Any] = {
            "agent_step_count": step_count,
            "tier2_invoked": True,
        }

        # If respond_to_user was called, extract structured output
        if structured_call:
            args = structured_call.get("args", {})
            user_msg = str(args.get("message", "")).strip()
            res_dict["user_response"] = user_msg
            res_dict["intent"] = str(args.get("intent", "general"))
            if args.get("resolved_place"):
                res_dict["resolved_place"] = str(args.get("resolved_place"))

            if not action_tool_calls:
                # respond_to_user was the only call -> clean termination
                has_tool_calls = False
                ai_msg.tool_calls = []
                ai_msg.content = user_msg
            else:
                # Action tools need execution first
                has_tool_calls = True
                ai_msg.tool_calls = action_tool_calls
        else:
            has_tool_calls = bool(raw_tool_calls)

        updated_messages = agent_messages + [ai_msg]
        res_dict["agent_messages"] = updated_messages

        content_text = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content or "")

        audit.log(
            node_name="tier2_agent",
            action=f"turn_{step_count}",
            category="LLM",
            event_id=event_id,
            input_summary={"step": step_count, "has_tool_calls": has_tool_calls},
            output_summary={
                "tool_calls_count": len(getattr(ai_msg, "tool_calls", [])),
                "content_preview": content_text[:120],
            },
            model_id=OPENROUTER_MODEL_TIER2,
        )

        # If agent emitted a final answer (no tool calls), or reached step limit, set user_response
        if not has_tool_calls or step_count >= AGENT_MAX_ITERATIONS:
            if "user_response" not in res_dict:
                import re
                # Clean unrendered markdown asterisks (**bold** -> bold) and markdown headings
                cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", content_text)
                cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE).strip()
                res_dict["user_response"] = cleaned
                res_dict["intent"] = "general"

        return res_dict

    def _build_user_prompt(self, state: JarvisState) -> str:
        uid = state.get("uid", "")
        raw_cmd = state.get("raw_request", {})
        cmd_text = raw_cmd.get("text", "") or state.get("user_command", "")
        packet = state.get("context_packet", {})
        session = state.get("session", {})
        tier1_resp = state.get("tier1_response", {})

        now_utc = datetime.now(timezone.utc)
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        now_ist = now_utc.astimezone(ist_offset)

        sections = [
            f"User Request: \"{cmd_text}\"",
            f"Current Time: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')} ({now_ist.strftime('%I:%M %p IST, %A %d %b %Y')})",
        ]

        # Resolved context from Tier 1 if available
        if tier1_resp:
            place = tier1_resp.get("resolved_place")
            vehicle = tier1_resp.get("resolved_vehicle")
            if place:
                sections.append(f"Resolved Location Context: {place}")
            if vehicle:
                sections.append(f"Resolved Vehicle Context: {vehicle}")

        if session:
            sections.append(f"Active Session State: {session.get('status', 'IDLE')} (Vehicle: {session.get('vehicle_class', 'Hunter 350')})")

        # Active reminders and saved places in database for context
        if uid:
            try:
                from ...cloud.tier2_agent_tools import is_test_environment
                if not is_test_environment():
                    from ...services.firestore_service import FirestoreService
                    fs = FirestoreService()
                    if fs.is_available:
                        for r in fs.get_reminders(uid):
                            self.db.create_reminder(uid, r)
                        for p in fs.get_places(uid):
                            self.db.create_place(uid, p)
                active_rems = self.db.list_reminders(uid, status="ACTIVE", limit=15)
                if active_rems:
                    rem_lines = []
                    for r in active_rems:
                        loc = f" | Location: {r.get('location_name')}" if r.get("location_name") else ""
                        act = f" | Activity: {r.get('activity')}" if r.get("activity") else ""
                        due = f" | Due: {r.get('due_at')}" if r.get("due_at") else ""
                        rem_lines.append(f"  • ID: {r['id']} | Title: \"{r['title']}\"{loc}{act}{due}")
                    sections.append("Existing Active Reminders:\n" + "\n".join(rem_lines))
            except Exception as re_err:
                logger.debug("Error listing active reminders for prompt: %s", re_err)

        gps = packet.get("gps", {})
        lat = gps.get("latitude") if isinstance(gps, dict) else None
        lon = gps.get("longitude") if isinstance(gps, dict) else None

        if lat is not None and lon is not None and (lat != 0.0 or lon != 0.0):
            # Check proximity to user's saved places
            saved_place_matches = []
            exact_location_summary = None
            if uid:
                try:
                    places = self.db.list_places(uid)
                    for p in places:
                        plat = p.get("latitude")
                        plon = p.get("longitude")
                        if plat is not None and plon is not None and (plat != 0.0 or plon != 0.0):
                            d_m = _haversine_m(lat, lon, plat, plon)
                            radius = p.get("radius_m", 150.0) or 150.0
                            label = p.get("user_label") or p.get("alias") or p.get("category") or "place"
                            if d_m <= 40.0:
                                saved_place_matches.append(f"CURRENTLY AT saved place '{p.get('name')}' ({label}, exact location match, ~{int(d_m)}m)")
                                if not exact_location_summary:
                                    exact_location_summary = f"CURRENTLY AT saved place '{p.get('name')}' ({label})"
                            elif d_m <= radius:
                                saved_place_matches.append(f"At saved place '{p.get('name')}' ({label}, inside compound/geofence, ~{int(d_m)}m)")
                                if not exact_location_summary:
                                    exact_location_summary = f"Inside saved place '{p.get('name')}' ({label})"
                            elif d_m <= 1500.0:
                                saved_place_matches.append(f"Near saved place '{p.get('name')}' ({label}, ~{int(d_m)}m away)")
                except Exception as pe:
                    logger.debug("Error checking saved places proximity: %s", pe)

            # 1. Google Places landmarks
            nearby_pois = packet.get("nearby_pois", [])
            if not nearby_pois:
                try:
                    from ...services.places_client import PlacesClient
                    client = PlacesClient()
                    pois = client.search_nearby(lat, lon, radius_m=250.0, uid=uid, max_results=5)
                    if pois:
                        nearby_pois = [p.model_dump() for p in pois]
                except Exception as pe:
                    logger.debug("Places API lookup skipped in prompt: %s", pe)

            poi_lines = []
            building_poi = None
            if nearby_pois:
                for p in nearby_pois[:5]:
                    name = p.get("name") or p.get("display_name")
                    cat = (p.get("category") or "place").replace("_", " ")
                    dist = int(p.get("distance_m", 0))
                    if name:
                        if dist <= 65 and ("apartment" in cat or "building" in cat or "residential" in cat or "complex" in cat or "premise" in cat):
                            poi_lines.append(f"{name} (CURRENT BUILDING / PREMISE, {cat})")
                            if not building_poi:
                                building_poi = f"{name} ({cat})"
                        else:
                            poi_lines.append(f"{name} ({cat}, ~{dist}m away)")

            # Resolve address
            resolved_address = reverse_geocode_location(lat, lon)

            # Fallback exact location summary to current building premise if no saved place match
            if not exact_location_summary and building_poi:
                exact_location_summary = f"Inside/at {building_poi}"

            # Append location sections with exact location prominently displayed first
            if exact_location_summary:
                sections.append(f"User Current Location: {exact_location_summary}")
            if saved_place_matches:
                sections.append("Saved Places Proximity: " + "; ".join(saved_place_matches))
            if poi_lines:
                sections.append("Immediate Landmarks (Google Places): " + ", ".join(poi_lines))
            if resolved_address:
                sections.append(f"Neighbourhood / Area: {resolved_address}")

            # Internal coordinates (do not recite to user)
            sections.append(f"[Internal GPS Reference: {lat:.5f}, {lon:.5f} - Do NOT speak raw coordinates to user unless explicitly asked]")

        return "\n".join(sections)
