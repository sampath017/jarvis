"""
SQLite Database Connection and Initialization Management.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ...settings import LOCAL_DB_PATH
from .schema import SCHEMA_SQL

logger = logging.getLogger(__name__)

_db_path: Path | None = None
_initialized_dbs: set[Path] = set()


def get_db_path() -> Path:
    """Return the absolute path to the local SQLite database file."""
    global _db_path
    if _db_path is None:
        p = Path(LOCAL_DB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        _db_path = p
    return _db_path


def init_database(db_path: Path | str | None = None, force: bool = False) -> None:
    """Create all SQL tables and set performance/concurrency PRAGMAs (runs once per db file)."""
    db_file = Path(db_path) if db_path else get_db_path()
    if not force and db_file in _initialized_dbs:
        return

    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _initialized_dbs.add(db_file)
    finally:
        conn.close()
    logger.info("SQLite database initialized at %s", db_file)
