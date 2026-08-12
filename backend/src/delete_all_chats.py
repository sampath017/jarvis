"""
Local script to delete all chat threads and messages from the local SQLite database.
"""

import sys
import sqlite3
from src.services.database import get_db_path


def main():
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
