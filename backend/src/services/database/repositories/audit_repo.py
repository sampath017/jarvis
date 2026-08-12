"""
Audit Entries & Run Summaries Repository — SQLite CRUD operations.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager


class AuditRepositoryMixin:
    """Mixin for audit_entries table and derived run summary queries."""

    _conn: Callable[[], ContextManager[sqlite3.Connection]]

    def insert_audit_entry(self, entry: dict[str, Any]) -> None:
        """Insert a single audit entry into the audit_entries table."""
        now = datetime.now(timezone.utc).isoformat()
        entry_id = entry.get("entry_id") or str(uuid.uuid4())
        input_summary = entry.get("input_summary", {})
        if not isinstance(input_summary, str):
            input_summary = json.dumps(input_summary)
        output_summary = entry.get("output_summary", {})
        if not isinstance(output_summary, str):
            output_summary = json.dumps(output_summary)

        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO audit_entries
                   (id, uid, run_id, event_id, node_name, action, category,
                    input_summary, output_summary, gps_lat, gps_lon,
                    model_id, confidence, tokens_used, latency_ms,
                    execution_result, error_detail, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id, entry.get("uid", ""), entry.get("run_id", ""),
                    entry.get("event_id"), entry.get("node_name", ""),
                    entry.get("action", ""), entry.get("category", "SYSTEM"),
                    input_summary, output_summary,
                    entry.get("gps_lat"), entry.get("gps_lon"),
                    entry.get("model_id"), entry.get("confidence"),
                    entry.get("tokens_used", 0), entry.get("latency_ms", 0.0),
                    entry.get("execution_result", "success"),
                    entry.get("error_detail"), now,
                ),
            )

    def get_audit_entries_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Retrieve all audit entries for a specific run, ordered by creation time."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_entries WHERE run_id=? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for json_col in ("input_summary", "output_summary"):
                val = d.get(json_col)
                if isinstance(val, str):
                    try:
                        d[json_col] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results

    def get_run_summary(self, run_id: str) -> dict[str, Any] | None:
        """Derive a run summary from audit_entries."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT
                       uid,
                       MIN(created_at) AS started_at,
                       MAX(created_at) AS completed_at,
                       COUNT(*) AS entry_count,
                       GROUP_CONCAT(DISTINCT node_name) AS nodes_visited,
                       MAX(CASE WHEN execution_result != 'success' THEN execution_result END) AS worst_result,
                       MAX(CASE WHEN category = 'LLM' THEN model_id END) AS model_id,
                       SUM(CASE WHEN category = 'LLM' THEN tokens_used ELSE 0 END) AS total_tokens,
                       SUM(CASE WHEN category = 'LLM' THEN latency_ms ELSE 0 END) AS total_llm_latency_ms,
                       MAX(CASE WHEN execution_result = 'error' THEN error_detail END) AS error
                   FROM audit_entries
                   WHERE run_id = ?""",
                (run_id,),
            ).fetchone()
        if not row or row["uid"] is None:
            return None
        d = dict(row)
        d["run_id"] = run_id
        d["status"] = "error" if d.get("worst_result") == "error" else "completed"
        return d

    def list_runs(self, uid: str, limit: int = 20) -> list[dict[str, Any]]:
        """List recent runs for a user, derived from audit_entries."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT
                       run_id,
                       MIN(created_at) AS started_at,
                       MAX(created_at) AS completed_at,
                       COUNT(*) AS entry_count,
                       SUM(CASE WHEN category = 'LLM' THEN tokens_used ELSE 0 END) AS total_tokens,
                       MAX(CASE WHEN execution_result = 'error' THEN 'error' ELSE 'completed' END) AS status
                   FROM audit_entries
                   WHERE uid = ?
                   GROUP BY run_id
                   ORDER BY MIN(created_at) DESC
                   LIMIT ?""",
                (uid, limit),
            ).fetchall()
        return [dict(r) for r in rows]
