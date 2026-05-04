import os
from typing import Annotated, TypedDict, List, Union
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from src.firebase_config import db
from datetime import datetime
import uuid
from langfuse.langchain import CallbackHandler
from src.logger import logger


# Define the state
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    user_latitude: float
    user_longitude: float

# --- Tools ---

from src.mcp_server import add_task, list_tasks, add_note, list_notes, delete_task, update_task, get_note, update_note, delete_note

# --- Tools Wrapper for LangGraph ---

@tool
def add_task_tool(title: str, notes: str = "", due_date: str = None, reminder_time: str = None,
                  location_name: str = None, latitude: float = None, longitude: float = None,
                  location_trigger: str = None) -> str:
    """Add a new task to Jarvis. Dates should be in ISO format (YYYY-MM-DDTHH:MM:SS).
    'due_date' is the absolute deadline. 'reminder_time' is when to notify the user.
    For location-based reminders, provide location_name, latitude, longitude, and
    location_trigger ('ON_EXIT' or 'ON_ENTER')."""
    return add_task(title, notes, due_date, reminder_time, location_name, latitude, longitude, location_trigger)

@tool
def list_tasks_tool(include_completed: bool = False) -> str:
    """List all tasks from Jarvis."""
    return list_tasks(include_completed)

@tool
def add_note_tool(title: str, content: str) -> str:
    """Add a new note to Jarvis."""
    return add_note(title, content)

@tool
def list_notes_tool() -> str:
    """List all notes from Jarvis."""
    return list_notes()

@tool
def get_note_tool(note_id: str) -> str:
    """Get the full content of a note. Use this before appending/editing a note."""
    return get_note(note_id)

@tool
def update_note_tool(note_id: str, title: str = None, content: str = None) -> str:
    """Update a note's title or content."""
    return update_note(note_id, title, content)

@tool
def delete_task_tool(task_id: str) -> str:
    """Delete a task from Jarvis. You must provide the task_id (found using list_tasks)."""
    return delete_task(task_id)

@tool
def delete_note_tool(note_id: str) -> str:
    """Delete a note from Jarvis. You must provide the note_id (found using list_notes)."""
    return delete_note(note_id)

@tool
def update_task_tool(task_id: str, is_completed: bool = None, title: str = None, due_date: str = None, reminder_time: str = None,
                     location_name: str = None, latitude: float = None, longitude: float = None,
                     location_trigger: str = None) -> str:
    """Update a task. Use this to change titles, mark as completed, change dates/reminders, or add/modify location-based reminders."""
    return update_task(task_id, is_completed, title, due_date, reminder_time, location_name, latitude, longitude, location_trigger)

@tool
def reverse_geocode_tool(latitude: float, longitude: float) -> str:
    """Convert GPS coordinates into a detailed human-readable address with building name,
    street, area, and city. Uses Google Maps Geocoding for high accuracy."""
    import httpx
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "Error: GOOGLE_API_KEY not set in environment."
        
        resp = httpx.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"latlng": f"{latitude},{longitude}", "key": api_key, "language": "en"},
            timeout=10,
        )
        data = resp.json()
        
        if data.get("status") != "OK" or not data.get("results"):
            return f"Could not resolve coordinates ({latitude}, {longitude}). Status: {data.get('status')}"
        
        # Google returns results from most specific to least specific
        results = data["results"]
        detailed_address = results[0].get("formatted_address", "Unknown")
        
        # Extract useful components
        components = results[0].get("address_components", [])
        parts = []
        for comp in components:
            types = comp.get("types", [])
            name = comp.get("long_name", "")
            if "premise" in types or "subpremise" in types:
                parts.append(f"Building/Flat: {name}")
            elif "street_number" in types:
                parts.append(f"Door No: {name}")
            elif "route" in types:
                parts.append(f"Street: {name}")
            elif "sublocality_level_1" in types or "sublocality" in types:
                parts.append(f"Area: {name}")
            elif "locality" in types:
                parts.append(f"City: {name}")
            elif "administrative_area_level_1" in types:
                parts.append(f"State: {name}")
            elif "postal_code" in types:
                parts.append(f"PIN: {name}")
        
        # Also grab the "plus code" for very precise location
        plus_code = data.get("plus_codes", {}).get("compound_code", "")
        
        output = f"📍 Address: {detailed_address}\n"
        if parts:
            output += "Details:\n" + "\n".join(f"  {p}" for p in parts)
        if plus_code:
            output += f"\nPlus Code: {plus_code}"
        return output
    except Exception as e:
        return f"Geocoding error: {str(e)}"

@tool
def get_location_context_tool(latitude: float, longitude: float) -> str:
    """Get comprehensive location intelligence. Returns:
    1) Precise address (building-level from Google Maps)
    2) Nearby places (shops, restaurants, ATMs within 300m)
    3) Which location-based tasks are nearby (with distance)
    Use this proactively when the user asks about their surroundings."""
    import math
    import httpx
    results = []
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    
    # 1. Reverse geocode with Google Maps
    try:
        resp = httpx.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"latlng": f"{latitude},{longitude}", "key": api_key, "language": "en"},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            results.append(f"📍 You are at: {data['results'][0]['formatted_address']}")
        else:
            results.append(f"📍 Coordinates: {latitude}, {longitude}")
    except Exception as e:
        results.append(f"📍 Coordinates: {latitude}, {longitude} (geocoding error: {e})")
    
    # 2. Nearby Places (Google Places API New)
    try:
        resp = httpx.post(
            "https://places.googleapis.com/v1/places:searchNearby",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.types,places.rating",
            },
            json={
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": latitude, "longitude": longitude},
                        "radius": 300.0,
                    }
                },
                "maxResultCount": 8,
                "languageCode": "en",
            },
            timeout=10,
        )
        places_data = resp.json()
        places = places_data.get("places", [])
        if places:
            results.append("\n🏪 Nearby Places (within 300m):")
            for p in places:
                name = p.get("displayName", {}).get("text", "Unknown")
                types = ", ".join(t.replace("_", " ") for t in p.get("types", [])[:2])
                addr = p.get("formattedAddress", "")
                rating = p.get("rating")
                rating_str = f" ⭐{rating}" if rating else ""
                results.append(f"  • {name} ({types}){rating_str} — {addr}")
    except Exception as e:
        results.append(f"\n🏪 Nearby places lookup failed: {e}")
    
    # 3. Check nearby location-based tasks
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    try:
        tasks_ref = db.collection("tasks").where("isCompleted", "==", False).stream()
        nearby_tasks = []
        for doc in tasks_ref:
            task = doc.to_dict()
            t_lat = task.get("latitude")
            t_lng = task.get("longitude")
            if t_lat and t_lng:
                dist = haversine(latitude, longitude, float(t_lat), float(t_lng))
                nearby_tasks.append({
                    "title": task.get("title"),
                    "location": task.get("locationName"),
                    "trigger": task.get("locationTrigger"),
                    "distance_m": round(dist),
                })
        
        if nearby_tasks:
            nearby_tasks.sort(key=lambda x: x["distance_m"])
            results.append("\n🗺️ Your Location Tasks:")
            for t in nearby_tasks:
                if t["distance_m"] <= 150:
                    status = "🔔 YOU ARE HERE"
                elif t["distance_m"] <= 500:
                    status = "📌 very close"
                elif t["distance_m"] <= 2000:
                    status = "🚶 walkable"
                else:
                    status = "🚗 drive"
                results.append(f"  - {t['title']} @ {t['location']} ({t['trigger']}) — {t['distance_m']}m [{status}]")
        else:
            results.append("\n🗺️ No location-based tasks set up.")
    except Exception as e:
        results.append(f"\nError checking tasks: {e}")
    
    return "\n".join(results)

tools = [add_task_tool, list_tasks_tool, add_note_tool, list_notes_tool, delete_task_tool, 
         update_task_tool, get_note_tool, update_note_tool, delete_note_tool,
         reverse_geocode_tool, get_location_context_tool]
import src.mcp_registry

# --- Graph ---
    all_tools = tools + src.mcp_registry.mcp_tools_list
    
    if os.environ.get("USE_VERTEX_AI") == "true":
        logger.info("Using Vertex AI Chat model (Enterprise)")
        return ChatVertexAI(
            model="gemini-1.5-flash", # Vertex names are slightly different
            temperature=0,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT")
        ).bind_tools(all_tools)
        
    return ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0).bind_tools(all_tools)

def call_model(state: AgentState):
    logger.debug("Entering 'agent' node: generating model response...")
    messages = state['messages']
    
    # Inject current date context and robust instructions
    import time
    local_tz = datetime.now().astimezone().tzinfo
    current_time = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    system_prompt = (
        f"You are Javris, a highly capable and proactive AI assistant. Current time is {current_time} (Timezone: {local_tz}).\n"
    )
    
    # Inject user's current GPS location if available
    user_lat = state.get('user_latitude')
    user_lng = state.get('user_longitude')
    if user_lat and user_lng:
        system_prompt += (
            f"USER'S CURRENT LOCATION: Latitude {user_lat}, Longitude {user_lng}. "
            f"When the user says 'my current location', 'here', 'where I am', etc., use these coordinates directly. "
            f"You have access to reverse_geocode_tool and get_location_context_tool — USE THEM proactively "
            f"to understand what area/address these coordinates correspond to. Never show raw coordinates to the user; "
            f"always resolve them to a human-readable address first.\n"
        )
    
    system_prompt += (
        "\nCRITICAL DIRECTIVES:\n"
        "1. TIMEZONE & DATES: You MUST calculate relative dates ('tomorrow', '3 PM') based on the current time and timezone. "
        "   When passing dates to any Calendar or scheduling tool, you MUST include the timezone offset (e.g., YYYY-MM-DDTHH:MM:SS+05:30) "
        "   so the event is created in the correct local time. Never use 'Z' (UTC) unless explicitly requested.\n"
        "2. TOOL CHAINING: If a user asks to modify or delete a task/note but didn't provide an ID, "
        "   you MUST call 'list_tasks' or 'list_notes' first to find the ID yourself. Do not ask the user for IDs.\n"
        "3. NOTE MERGING: Before adding a new note, always list existing notes to check for similar titles. "
        "   If a similar note exists, you MUST ask the user for confirmation to merge/append before calling any tools. "
        "   Never create duplicate notes for the same topic.\n"
        "4. FORMATTING: Never send raw time strings like '10:00:00' to the database; always include the date.\n"
        "5. UI PRESENTATION: NEVER show raw database IDs or raw GPS coordinates to the user. "
        "   Always use human-readable names (addresses, area names, landmarks).\n"
        "6. DATE PRESENTATION: When mentioning dates or times to the user, ALWAYS convert them into human-readable, "
        "   conversational formats (e.g., 'Tomorrow at 5:00 PM', 'Next Monday', 'May 4th'). Do NOT show raw ISO timestamps.\n"
        "7. FIELD ACCURACY: ONLY use the fields defined in the tool schemas (title, notes, due_date, reminder_time). "
        "   NEVER invent or mention non-existent fields like 'Priority', 'Category', or 'Tags'.\n"
        "8. DEADLINE VS REMINDER: 'due_date' is the absolute deadline (when the task must be finished). "
        "   'reminder_time' is for notifications. You can set both. If the user says 'Remind me tomorrow at 5pm about the project due Friday', "
        "   set reminder_time to tomorrow 5pm and due_date to Friday.\n"
        "9. TITLE CLEANLINESS: The 'title' field should ONLY contain the name of the task. "
        "   DO NOT include deadlines, reminders, or other metadata inside the title string itself.\n"
        "9. RESPONSIVENESS: Be concise, helpful, and proactive. Use Markdown formatting to make your responses readable.\n"
        "10. LOCATION-BASED REMINDERS: When a user says things like 'remind me to buy milk when I leave the office' or "
        "   'notify me to pick up groceries when I'm near the supermarket', create a task with location fields. "
        "   Use location_trigger='ON_EXIT' for 'when I leave' and 'ON_ENTER' for 'when I arrive/am near'. "
        "   You MUST provide latitude/longitude coordinates for the location. If the user says 'my current location', "
        "   'here', or 'home' without coordinates, use the USER'S CURRENT LOCATION provided above. "
        "   Always confirm the location name and trigger type in your response.\n"
        "11. PROACTIVE LOCATION INTELLIGENCE: When the user asks 'where am I?', 'what's nearby?', "
        "   or anything about their surroundings, ALWAYS call get_location_context_tool with their coordinates. "
        "   This gives you their resolved address AND any nearby location-based tasks. "
        "   When the user mentions a place name you don't have coordinates for, use reverse_geocode_tool to look it up. "
        "   Think like a smart assistant on a bike — the user is moving, so be proactive about alerting them "
        "   to nearby tasks and relevant location context."
    )
    
    # Add system message at the beginning if not present
    if not any(isinstance(m, HumanMessage) for m in messages): # This is a simplification
        pass 
    
    # We'll prepend it for the model call
    full_messages = [HumanMessage(content=system_prompt)] + messages
    
    model = get_model()
    response = model.invoke(full_messages)
    
    if hasattr(response, "tool_calls") and response.tool_calls:
        logger.info(f"Model decided to call tools: {[t['name'] for t in response.tool_calls]}")
    else:
        logger.info("Model provided final text response.")
        
    return {"messages": [response]}

def should_continue(state: AgentState):
    last_message = state['messages'][-1]
    if last_message.tool_calls:
        logger.debug("Routing to 'tools' node...")
        return "tools"
    logger.debug("Routing to END...")
    return END

def get_workflow():
    all_tools = tools + src.mcp_registry.mcp_tools_list
    tool_node = ToolNode(all_tools)
    
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    return workflow

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def run_agent(query: str, thread_id: str = "javris_user_1", thread_title: str = "Chat Session",
                    user_latitude: float = None, user_longitude: float = None):
    try:
        workflow = get_workflow()
        async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as memory:
            await memory.setup()
            app = workflow.compile(checkpointer=memory)
            
            # Initialize Langfuse handler
            langfuse_handler = CallbackHandler()
            
            inputs = {
                "messages": [HumanMessage(content=query)],
                "user_latitude": user_latitude or 0.0,
                "user_longitude": user_longitude or 0.0,
            }
            # Add configurable thread_id to keep conversation history
            config = {
                "recursion_limit": 50,
                "configurable": {"thread_id": thread_id},
                "tags": [f"Chat: {thread_title}"],
                "metadata": {
                    "langfuse_session_id": thread_id,
                    "langfuse_user_id": "javris_user",
                    "langfuse_trace_name": f"{query[:50]}"
                },
                "callbacks": [langfuse_handler]
            }
            
            final_state = await app.ainvoke(inputs, config=config)
        last_message = final_state["messages"][-1]
        
        content = last_message.content
        
        # Handle list of content blocks (common in multimodal or complex responses)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
            return " ".join(text_parts) if text_parts else "I processed your request but had trouble formatting the response."
        
        return str(content)
    except Exception as e:
        logger.error(f"AGENT EXECUTION ERROR: {str(e)}")
        return f"Internal Error: {str(e)}"
