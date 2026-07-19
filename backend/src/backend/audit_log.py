"""
Structured Audit Logging

Logs every model decision and function call with full traceability.
In production, audit entries are stored in Firestore under
users/{uid}/agentRuns/{runId}. This module manages the in-request
audit buffer that is flushed to Firestore at the end of each graph run.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..models.schemas import AuditEntry

logger = logging.getLogger(__name__)


class AuditLog:
    """
    In-request audit buffer.

    Collects AuditEntry records during a single graph invocation,
    then provides them for persistence to Firestore by the persist node.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def log(
        self,
        event_id: str,
        component: str,
        action: str,
        input_ref: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        confidence: float | None = None,
        model_id: str | None = None,
        execution_result: str = "success",
        error_detail: str | None = None,
    ) -> AuditEntry:
        """Create and store an audit entry."""
        entry = AuditEntry(
            timestamp=datetime.utcnow(),
            event_id=event_id,
            component=component,
            action=action,
            input_ref=input_ref or {},
            output=output or {},
            confidence=confidence,
            model_id=model_id,
            execution_result=execution_result,
            error_detail=error_detail,
        )
        self._entries.append(entry)
        logger.debug(
            "audit: component=%s action=%s result=%s",
            component, action, execution_result,
        )
        return entry

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def get_entries_for_event(self, event_id: str) -> list[AuditEntry]:
        """Get all audit entries related to a specific event."""
        return [e for e in self._entries if e.event_id == event_id]

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialise all entries for Firestore storage."""
        return [entry.model_dump(mode="json") for entry in self._entries]

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    def summary(self) -> dict[str, Any]:
        """Generate a summary of the audit log."""
        by_component: dict[str, int] = {}
        by_result: dict[str, int] = {}
        for entry in self._entries:
            by_component[entry.component] = by_component.get(entry.component, 0) + 1
            by_result[entry.execution_result] = by_result.get(entry.execution_result, 0) + 1
        return {
            "total_entries": len(self._entries),
            "by_component": by_component,
            "by_result": by_result,
        }
