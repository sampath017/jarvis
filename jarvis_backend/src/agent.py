import os
from typing import Annotated, TypedDict, List, Union
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from src.firebase_config import db
from datetime import datetime
import uuid

# Define the state
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]

# --- Tools ---

from src.mcp_server import add_task, list_tasks, add_note, list_notes, delete_task, update_task, get_note, update_note, delete_note

# --- Tools Wrapper for LangGraph ---

@tool
def add_task_tool(title: str, notes: str = "", due_date: str = None, reminder_time: str = None) -> str:
    """Add a new task to Jarvis. Dates should be in ISO format (YYYY-MM-DDTHH:MM:SS)."""
    return add_task(title, notes, due_date, reminder_time)

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
def update_task_tool(task_id: str, is_completed: bool = None, title: str = None, due_date: str = None, reminder_time: str = None) -> str:
    """Update a task. Use this to change titles, mark as completed, or change dates/reminders."""
    return update_task(task_id, is_completed, title, due_date, reminder_time)

tools = [add_task_tool, list_tasks_tool, add_note_tool, list_notes_tool, delete_task_tool, update_task_tool, get_note_tool, update_note_tool, delete_note_tool]
tool_node = ToolNode(tools)

# --- Graph ---

def get_model():
    # Use Gemini 3 Flash for maximum performance
    return ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0).bind_tools(tools)

def call_model(state: AgentState):
    messages = state['messages']
    
    # Inject current date context and robust instructions
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        f"You are Javris, a highly capable AI assistant. Current time is {current_time}.\n\n"
        "CRITICAL DIRECTIVES:\n"
        "1. TASK MANAGEMENT: Always use full ISO 8601 timestamps (YYYY-MM-DDTHH:MM:SS) for dates. "
        "   Calculate relative dates (like 'tomorrow' or 'next Monday') based on the current time.\n"
        "2. TOOL CHAINING: If a user asks to modify or delete a task/note but didn't provide an ID, "
        "   you MUST call 'list_tasks' or 'list_notes' first to find the ID yourself. Do not ask the user for IDs.\n"
        "3. NOTE MERGING: Before adding a new note, always list existing notes to check for similar titles. "
        "   If a similar note exists, you MUST ask the user for confirmation to merge/append before calling any tools. "
        "   Never create duplicate notes for the same topic.\n"
        "4. FORMATTING: Never send raw time strings like '10:00:00' to the database; always include the date.\n"
        "5. RESPONSIVENESS: Be concise, helpful, and proactive."
    )
    
    # Add system message at the beginning if not present
    if not any(isinstance(m, HumanMessage) for m in messages): # This is a simplification
        pass 
    
    # We'll prepend it for the model call
    full_messages = [HumanMessage(content=system_prompt)] + messages
    
    model = get_model()
    response = model.invoke(full_messages)
    return {"messages": [response]}

def should_continue(state: AgentState):
    last_message = state['messages'][-1]
    if last_message.tool_calls:
        return "tools"
    return END

workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

from langgraph.checkpoint.memory import MemorySaver

memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

async def run_agent(query: str):
    try:
        inputs = {"messages": [HumanMessage(content=query)]}
        # Safety Net: Limit to 15 loops. 5 was too restrictive for multi-step tasks 
        # (like list_notes -> get_note -> update_note).
        # Add configurable thread_id to keep conversation history
        config = {
            "recursion_limit": 15,
            "configurable": {"thread_id": "javris_user_1"}
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
        print(f"AGENT EXECUTION ERROR: {str(e)}")
        return f"I encountered an error while processing your request: {str(e)}"
