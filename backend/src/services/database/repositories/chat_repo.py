"""
Chat Threads and Messages Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class ChatRepositoryMixin:
    """Mixin for chat_threads and chat_messages tables."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def append_chat_message(self, uid: str, thread_id: str, message: dict[str, Any]) -> dict[str, Any]:
        msg_id = message.get("message_id", message.get("id", str(uuid.uuid4())))
        now = datetime.now(timezone.utc).isoformat()
        ts = message.get("timestamp", now)

        with self._conn() as conn:
            # Ensure thread exists
            existing_thread = conn.execute(
                "SELECT id FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if not existing_thread:
                title = (str(message.get("content", ""))[:48] if message.get("role") == "user" else "New chat") or "New chat"
                conn.execute(
                    """INSERT INTO chat_threads (id, uid, title, last_message_preview, created_at, updated_at)
                       VALUES (?,?,?,?,?,?)""",
                    (thread_id, uid, title, str(message.get("content", ""))[:140], now, now),
                )
            else:
                conn.execute(
                    "UPDATE chat_threads SET last_message_preview=?, updated_at=? WHERE id=?",
                    (str(message.get("content", ""))[:140], now, thread_id),
                )

            conn.execute(
                """INSERT OR REPLACE INTO chat_messages (id, uid, thread_id, role, content, run_id, timestamp, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    msg_id, uid, thread_id, message.get("role", "user"),
                    message.get("content", ""), message.get("run_id"), str(ts), now,
                ),
            )
        return {"id": msg_id, "uid": uid, "thread_id": thread_id, **message}

    def get_recent_messages(self, uid: str, thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE uid = ? AND thread_id = ? ORDER BY timestamp DESC LIMIT ?",
                (uid, thread_id, limit),
            ).fetchall()
        messages = [dict(r) for r in rows]
        messages.reverse()
        return messages
