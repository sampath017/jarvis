"""
Structured Audit Logging

Logs every node decision, LLM call, and function execution with full
end-to-end traceability. Each audit entry is written directly to the
local SQLite audit_entries table and also emitted as a structured log line.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from ..models.schemas import AuditEntry
from ..services.database import DatabaseService

logger = logging.getLogger(__name__)


class AuditLog:
    """
    Per-run audit logger.

    Created once per graph invocation with the run's uid and run_id.
    Every call to ``log()`` writes directly to the ``audit_entries``
    SQL table and emits a structured log line for debugging.
    """

    def __init__(
        self,
        db: DatabaseService,
        uid: str,
        run_id: str,
    ) -> None:
        self._db = db
        self._uid = uid
        self._run_id = run_id
        self._entries: list[AuditEntry] = []

    # ── Core logging method ──────────────────────────────────────────────

    def log(
        self,
        node_name: str,
        action: str,
        *,
        category: str = "SYSTEM",
        event_id: str = "",
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        gps_lat: float | None = None,
        gps_lon: float | None = None,
        model_id: str | None = None,
        confidence: float | None = None,
        tokens_used: int = 0,
        latency_ms: float = 0.0,
        execution_result: str = "success",
        error_detail: str | None = None,
    ) -> AuditEntry:
        """Create, persist, and return an audit entry."""
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            uid=self._uid,
            run_id=self._run_id,
            event_id=event_id,
            node_name=node_name,
            action=action,
            category=category,
            input_summary=input_summary or {},
            output_summary=output_summary or {},
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            model_id=model_id,
            confidence=confidence,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            execution_result=execution_result,
            error_detail=error_detail,
        )
        self._entries.append(entry)

        # Persist to SQL immediately
        try:
            self._db.insert_audit_entry(entry.model_dump(mode="json"))
        except Exception as exc:
            logger.critical("Failed to persist audit entry to DB: %s", exc, exc_info=True)

        # Also emit a structured log line for debugging / log file capture
        logger.info(
            "AUDIT [%s] %s -> %s (%s)",
            entry.node_name,
            entry.action,
            entry.execution_result,
            entry.category,
            extra={
                "audit_entry_id": entry.entry_id,
                "run_id": self._run_id,
                "uid": self._uid,
                "node": entry.node_name,
                "action": entry.action,
                "category": entry.category,
                "result": entry.execution_result,
            },
        )
        return entry

    # ── Convenience accessors ────────────────────────────────────────────

    @property
    def entries(self) -> list[AuditEntry]:
        """Return a copy of all entries logged during this run."""
        return list(self._entries)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialise all entries (backward compat with persist node)."""
        return [entry.model_dump(mode="json") for entry in self._entries]

    def summary(self) -> dict[str, Any]:
        """Generate a summary of the audit log."""
        by_node: dict[str, int] = {}
        by_result: dict[str, int] = {}
        for entry in self._entries:
            by_node[entry.node_name] = by_node.get(entry.node_name, 0) + 1
            by_result[entry.execution_result] = by_result.get(entry.execution_result, 0) + 1
        return {
            "total_entries": len(self._entries),
            "by_node": by_node,
            "by_result": by_result,
        }


def audit_from_state(state: dict, db: DatabaseService | None = None) -> AuditLog:
    """Create an AuditLog instance from LangGraph state.

    Convenience factory for graph nodes — extracts uid and run_id
    from the state dict and creates a ready-to-use AuditLog.
    """
    return AuditLog(
        db=db or DatabaseService(),
        uid=state.get("uid", ""),
        run_id=state.get("run_id", ""),
    )
