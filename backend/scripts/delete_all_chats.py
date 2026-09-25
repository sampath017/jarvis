"""
Maintenance Script: Delete all chat threads and messages from the local SQLite database.
Usage:
    uv run python -m scripts.delete_all_chats
    # or
    python backend/scripts/delete_all_chats.py
"""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from src.services.database import get_db_path


def main() -> None:
    print("Connecting to local SQLite database...")
    try:
        db_path = get_db_path()
        with sqlite3.connect(db_path) as conn:
            c1 = conn.execute("DELETE FROM chat_messages")
            c2 = conn.execute("DELETE FROM chat_threads")
            conn.commit()

        print(f"Deleted {c2.rowcount} thread(s) and {c1.rowcount} message(s).")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
