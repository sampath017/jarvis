"""
FR-12: In-Memory CRUD Store

Provides authenticated CRUD operations for all supported entities.
Only accessible through the function registry — never directly by an LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..models.enums import CRUDEntity


class CRUDStore:
    """
    In-memory CRUD store for all Jarvis entities.

    Supports: REMINDER, TASK, NOTE, PLACE, SESSION, PREFERENCE, AUTOMATION, EVENT
    """

    def __init__(self) -> None:
        self._stores: dict[CRUDEntity, dict[str, dict[str, Any]]] = {
            entity: {} for entity in CRUDEntity
        }

    def create(self, entity: CRUDEntity, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new record. Returns the created record with generated ID."""
        record_id = str(uuid.uuid4())
        record = {
            "id": record_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            **data,
        }
        self._stores[entity][record_id] = record
        return record

    def read(self, entity: CRUDEntity, record_id: str) -> dict[str, Any] | None:
        """Read a single record by ID."""
        return self._stores[entity].get(record_id)

    def update(
        self, entity: CRUDEntity, record_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing record. Returns updated record or None."""
        if record_id not in self._stores[entity]:
            return None
        record = self._stores[entity][record_id]
        record.update(data)
        record["updated_at"] = datetime.now().isoformat()
        return record

    def delete(self, entity: CRUDEntity, record_id: str) -> bool:
        """Delete a record. Returns True if deleted, False if not found."""
        if record_id in self._stores[entity]:
            del self._stores[entity][record_id]
            return True
        return False

    def list_all(
        self, entity: CRUDEntity, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """List all records of an entity, optionally filtered."""
        records = list(self._stores[entity].values())
        if filters:
            for key, value in filters.items():
                records = [r for r in records if r.get(key) == value]
        return records

    def count(self, entity: CRUDEntity) -> int:
        """Count records for an entity type."""
        return len(self._stores[entity])

    def clear(self, entity: CRUDEntity | None = None) -> None:
        """Clear all records, or records of a specific entity type."""
        if entity:
            self._stores[entity] = {}
        else:
            for e in CRUDEntity:
                self._stores[e] = {}
