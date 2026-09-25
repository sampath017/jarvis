"""
Maintenance Script: Purge all chat_sessions and chat_messages from Cloud Firestore.
Usage:
    uv run python -m scripts.purge_chats
    # or
    python backend/scripts/purge_chats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from src.services.firestore_service import FirestoreService


def purge() -> None:
    fs = FirestoreService()
    if not fs.is_available:
        print("Error: Firestore is not available.", file=sys.stderr)
        sys.exit(1)

    print("Purging chat_sessions and chat_messages from Firestore...")

    # 1. Purge chat_messages
    msgs = list(fs._db.collection("chat_messages").stream())
    print(f"Found {len(msgs)} chat message(s). Deleting...")
    for m in msgs:
        m.reference.delete()

    # 2. Purge chat_sessions
    sessions = list(fs._db.collection("chat_sessions").stream())
    print(f"Found {len(sessions)} chat session(s). Deleting...")
    for s in sessions:
        s.reference.delete()

    print(f"Successfully purged {len(sessions)} session(s) and {len(msgs)} message(s) from Firestore.")


if __name__ == "__main__":
    purge()
