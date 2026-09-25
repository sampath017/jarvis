"""
Forwarder for backward compatibility: use backend/scripts/purge_chats.py directly or 'uv run purge-chats'.
"""

from scripts.purge_chats import purge

if __name__ == "__main__":
    purge()
