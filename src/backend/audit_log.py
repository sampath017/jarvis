"""
FR-13: Structured Audit Logging

Logs every model decision and function call with full traceability.
Uses JSON-Lines format for easy querying during evaluation.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import AUDIT_LOG_FILE
from ..models.schemas import AuditEntry


class AuditLog:
    """
    Append-only structured audit log.

    Every decision point in the pipeline creates an AuditEntry with:
    - event_id: which event triggered this
    - component: which module made the decision
    - action: what happened
    - input_ref: summary of inputs
    - output: summary of outputs
    - confidence: decision confidence
    - model_id: which model (if LLM was used)
    - execution_result: success/rejected/error
    """

    def __init__(self, log_dir: Path | None = None) -> None:
        self._entries: list[AuditEntry] = []
        self._log_dir = log_dir

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
            timestamp=datetime.now(),
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
        return entry

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def get_entries_for_event(self, event_id: str) -> list[AuditEntry]:
        """Get all audit entries related to a specific event."""
        return [e for e in self._entries if e.event_id == event_id]

    def get_entries_for_component(self, component: str) -> list[AuditEntry]:
        """Get all audit entries from a specific component."""
        return [e for e in self._entries if e.component == component]

    def save(self, filepath: Path | None = None) -> Path:
        """Save all entries to a JSONL file."""
        path = filepath or (self._log_dir / AUDIT_LOG_FILE if self._log_dir else Path(AUDIT_LOG_FILE))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(entry.model_dump_json() + "\n")
        return path

    def clear(self) -> None:
        """Clear all entries (for test isolation)."""
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
