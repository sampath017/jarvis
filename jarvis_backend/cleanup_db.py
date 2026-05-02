import os
import sys
from datetime import datetime

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from src.firebase_config import db

def cleanup():
    print("Starting database cleanup...")
    
    # Check Tasks
    tasks_ref = db.collection("tasks")
    tasks = tasks_ref.stream()
    deleted_count = 0
    
    for task in tasks:
        data = task.to_dict()
        task_id = task.id
        invalid = False
        
        due_date = data.get("dueDate")
        reminder_time = data.get("reminderTime")
        
        # Check for invalid format (e.g. "20:00:00")
        if due_date and (len(due_date) < 10 or "T" not in due_date):
            print(f"Found invalid dueDate '{due_date}' in task {task_id}")
            invalid = True
            
        if reminder_time and (len(reminder_time) < 10 or "T" not in reminder_time):
            print(f"Found invalid reminderTime '{reminder_time}' in task {task_id}")
            invalid = True
            
        if invalid:
            tasks_ref.document(task_id).delete()
            deleted_count += 1
            print(f"Deleted task {task_id}")

    print(f"Cleanup finished. Deleted {deleted_count} invalid tasks.")

if __name__ == "__main__":
    cleanup()
