import os
import sys

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from src.firebase_config import db

def clear_chats():
    print("Deleting all chats...")
    chats_ref = db.collection("chats")
    chats = chats_ref.stream()
    count = 0
    for chat in chats:
        chats_ref.document(chat.id).delete()
        count += 1
    print(f"Deleted {count} chats.")

if __name__ == "__main__":
    clear_chats()
