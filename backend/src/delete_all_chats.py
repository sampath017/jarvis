"""
Forwarder for backward compatibility: use backend/scripts/delete_all_chats.py directly or 'uv run delete-chats'.
"""

from scripts.delete_all_chats import main

if __name__ == "__main__":
    main()
