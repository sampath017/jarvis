from fastmcp import FastMCP
from src.firebase_config import db
from datetime import datetime
import uuid

# Initialize FastMCP server
mcp = FastMCP("Javris")

def _fix_date(date_str: str) -> str:
    if not date_str:
        return None
    # If it's just a time like HH:MM:SS, prepend today's date
    if len(date_str) <= 8 and ":" in date_str:
        return f"{datetime.now().strftime('%Y-%m-%d')}T{date_str}"
    return date_str

@mcp.tool()
def add_task(title: str, notes: str = "", due_date: str = None, reminder_time: str = None) -> str:
    """Add a new task to Jarvis. Dates should be in ISO format (YYYY-MM-DDTHH:MM:SS)."""
    task_id = str(uuid.uuid4())
    due_date = _fix_date(due_date)
    reminder_time = _fix_date(reminder_time)
    task_data = {
        "id": task_id,
        "title": title,
        "notes": notes,
        "isCompleted": False,
        "createdAt": datetime.now(),
        "dueDate": due_date,
        "reminderTime": reminder_time
    }
    db.collection("tasks").document(task_id).set(task_data)
    return f"Task '{title}' added successfully."

@mcp.tool()
def list_tasks(include_completed: bool = False) -> str:
    """List all tasks from Jarvis."""
    tasks_ref = db.collection("tasks")
    if not include_completed:
        docs = tasks_ref.where("isCompleted", "==", False).stream()
    else:
        docs = tasks_ref.stream()
    
    tasks = []
    for doc in docs:
        d = doc.to_dict()
        tasks.append(f"- [{ 'x' if d.get('isCompleted') else ' ' }] {d.get('title')} (ID: {d.get('id')})")
    
    if not tasks:
        return "You have no active tasks."
    return "\n".join(tasks)

@mcp.tool()
def add_note(title: str, content: str) -> str:
    """Add a new note to Jarvis."""
    note_id = str(uuid.uuid4())
    note_data = {
        "id": note_id,
        "title": title,
        "content": content,
        "createdAt": datetime.now()
    }
    db.collection("notes").document(note_id).set(note_data)
    return f"Note '{title}' added successfully."

@mcp.tool()
def list_notes() -> str:
    """List all notes from Jarvis."""
    notes_ref = db.collection("notes")
    docs = notes_ref.order_by("createdAt", direction="DESCENDING").stream()
    
    notes = []
    for doc in docs:
        d = doc.to_dict()
        notes.append(f"- {d.get('title')} (ID: {d.get('id')}): {d.get('content')[:50]}...")
    
    if not notes:
        return "You have no notes."
    return "\n".join(notes)

@mcp.tool()
def delete_task(task_id: str) -> str:
    """Delete a task from Jarvis using its ID."""
    db.collection("tasks").document(task_id).delete()
    return f"Task {task_id} deleted successfully."

@mcp.tool()
def update_task(task_id: str, is_completed: bool = None, title: str = None, due_date: str = None, reminder_time: str = None) -> str:
    """Update an existing task. Use this to mark tasks as completed or change times."""
    task_ref = db.collection("tasks").document(task_id)
    if not task_ref.get().exists:
        return f"Task {task_id} not found."
        
    update_data = {}
    if is_completed is not None:
        update_data["isCompleted"] = is_completed
    if title is not None:
        update_data["title"] = title
    if due_date is not None:
        update_data["dueDate"] = _fix_date(due_date)
    if reminder_time is not None:
        update_data["reminderTime"] = _fix_date(reminder_time)
    
    if update_data:
        task_ref.update(update_data)
        return f"Task {task_id} updated successfully."
    return "No changes provided."

@mcp.tool()
def get_note(note_id: str) -> str:
    """Get the full content of a note by its ID."""
    doc = db.collection("notes").document(note_id).get()
    if doc.exists:
        d = doc.to_dict()
        return f"Title: {d.get('title')}\nContent: {d.get('content')}"
    return "Note not found."

@mcp.tool()
def update_note(note_id: str, title: str = None, content: str = None) -> str:
    """Update an existing note's title or content."""
    note_ref = db.collection("notes").document(note_id)
    if not note_ref.get().exists:
        return f"Note {note_id} not found."

    update_data = {}
    if title is not None:
        update_data["title"] = title
    if content is not None:
        update_data["content"] = content
    
    if update_data:
        note_ref.update(update_data)
        return f"Note {note_id} updated successfully."
    return "No changes provided."

@mcp.tool()
def delete_note(note_id: str) -> str:
    """Delete a note from Jarvis using its ID."""
    db.collection("notes").document(note_id).delete()
    return f"Note {note_id} deleted successfully."

if __name__ == "__main__":
    mcp.run()
