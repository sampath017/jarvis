"""
DatabaseService — Unified SQLite Service Layer.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from .connection import get_db_path, init_database
from .repositories import (
    AuditRepositoryMixin,
    AutomationsRepositoryMixin,
    ChatRepositoryMixin,
    ContextRulesRepositoryMixin,
    EventsRepositoryMixin,
    NotesRepositoryMixin,
    NotificationsRepositoryMixin,
    PlacesRepositoryMixin,
    PreferencesRepositoryMixin,
    RemindersRepositoryMixin,
    SessionsRepositoryMixin,
    TasksRepositoryMixin,
)


class DatabaseService(
    TasksRepositoryMixin,
    NotesRepositoryMixin,
    PlacesRepositoryMixin,
    PreferencesRepositoryMixin,
    AutomationsRepositoryMixin,
    RemindersRepositoryMixin,
    ContextRulesRepositoryMixin,
    NotificationsRepositoryMixin,
    SessionsRepositoryMixin,
    EventsRepositoryMixin,
    ChatRepositoryMixin,
    AuditRepositoryMixin,
):
    """Native SQL database operations for Jarvis."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path: Path = Path(db_path) if db_path else get_db_path()
        init_database(self._db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Open, commit/rollback, and close a short-lived SQLite connection.

        Explicitly closing here avoids locked database files and keeps
        concurrency reliable under async workloads.
        """
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Scoped Context Loader ────────────────────────────────────────────
    def load_scoped_context(self, uid: str, thread_id: str | None = None) -> dict[str, Any]:
        """Load essential user state for LangGraph nodes."""
        return {
            "session": self.get_active_session(uid),
            "tasks": self.list_tasks(uid, limit=10),
            "messages": self.get_recent_messages(uid, thread_id, limit=10) if thread_id else [],
            "preferences": self.list_preferences(uid, limit=20),
        }

    # ── Generic CRUD dispatch (for validate_and_execute node) ────────────
    _TABLE_CRUD = {
        "tasks": ("create_task", "get_task", "update_task", "delete_task", "list_tasks"),
        "notes": ("create_note", "get_note", "update_note", "delete_note", "list_notes"),
        "places": ("create_place", "get_place", "update_place", "delete_place", "list_places"),
        "preferences": ("create_preference", "get_preference", "update_preference", "delete_preference", "list_preferences"),
        "automations": ("create_automation", "get_automation", "update_automation", "delete_automation", "list_automations"),
        "contextEvents": (None, None, None, None, None),
        "mobilitySessions": (None, None, None, None, None),
    }

    def crud_create(self, uid: str, table: str, data: dict[str, Any]) -> dict[str, Any]:
        method_name = self._TABLE_CRUD.get(table, (None,))[0]
        if method_name:
            return getattr(self, method_name)(uid, data)
        raise ValueError(f"Create not supported for table '{table}'")

    def crud_get(self, uid: str, table: str, record_id: str) -> dict[str, Any] | None:
        method_name = self._TABLE_CRUD.get(table, (None, None))[1]
        if method_name:
            return getattr(self, method_name)(uid, record_id)
        raise ValueError(f"Get not supported for table '{table}'")

    def crud_update(self, uid: str, table: str, record_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        method_name = self._TABLE_CRUD.get(table, (None, None, None))[2]
        if method_name:
            return getattr(self, method_name)(uid, record_id, data)
        raise ValueError(f"Update not supported for table '{table}'")

    def crud_delete(self, uid: str, table: str, record_id: str) -> bool:
        method_name = self._TABLE_CRUD.get(table, (None, None, None, None))[3]
        if method_name:
            return getattr(self, method_name)(uid, record_id)
        raise ValueError(f"Delete not supported for table '{table}'")

    def crud_list(self, uid: str, table: str, limit: int = 20) -> list[dict[str, Any]]:
        method_name = self._TABLE_CRUD.get(table, (None, None, None, None, None))[4]
        if method_name:
            return getattr(self, method_name)(uid, limit=limit)
        raise ValueError(f"List not supported for table '{table}'")
