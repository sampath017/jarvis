"""
FR-11: Allow-Listed Function Registry with Schema Validation

Defines all permitted backend functions that Tier 2 may invoke.
Validates function calls against JSON schemas before execution.
The LLM never accesses the database directly — only through this interface.
"""

from __future__ import annotations

from typing import Any

from ..backend.crud_store import CRUDStore
from ..models.enums import CRUDEntity, CRUDOperation
from ..models.schemas import FunctionCall

# ── Function Definitions ─────────────────────────────────────────────────────
# Each entry: function_name → {entity, operation, required_args, optional_args}

ALLOWED_FUNCTIONS: dict[str, dict[str, Any]] = {
    "create_task": {
        "entity": CRUDEntity.TASK,
        "operation": CRUDOperation.CREATE,
        "required_args": ["title"],
        "optional_args": ["description", "due_date", "priority", "context_place", "trigger_place", "trigger_category"],
        "description": "Create a new task, optionally with a time due_date or location trigger_place",
    },
    "update_task": {
        "entity": CRUDEntity.TASK,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["id"],
        "optional_args": ["title", "description", "due_date", "priority", "status", "trigger_place", "trigger_category"],
        "description": "Update an existing task",
    },
    "create_note": {
        "entity": CRUDEntity.NOTE,
        "operation": CRUDOperation.CREATE,
        "required_args": ["content"],
        "optional_args": ["title", "place", "category", "tags"],
        "description": "Create a note, optionally associated with a place",
    },
    "update_note": {
        "entity": CRUDEntity.NOTE,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["id"],
        "optional_args": ["title", "content"],
        "description": "Update an existing note",
    },
    "update_note_by_title": {
        "entity": CRUDEntity.NOTE,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["title_match"],
        "optional_args": ["title", "content"],
        "description": "Update the most recently edited note whose title contains title_match",
    },
    "list_notes": {
        "entity": CRUDEntity.NOTE,
        "operation": CRUDOperation.LIST,
        "required_args": [],
        "optional_args": [],
        "description": "List the user's recent notes",
    },
    "delete_note": {
        "entity": CRUDEntity.NOTE,
        "operation": CRUDOperation.DELETE,
        "required_args": ["id"],
        "optional_args": [],
        "description": "Delete one user-owned note",
    },
    "create_reminder": {
        "entity": CRUDEntity.REMINDER,
        "operation": CRUDOperation.CREATE,
        "required_args": ["title"],
        "optional_args": [
            "body", "due_at", "location_name", "latitude", "longitude", "radius_m",
            "activity", "status", "one_shot",
        ],
        "description": "Create a reminder triggered by time, location, activity, or their combination",
    },
    "update_reminder": {
        "entity": CRUDEntity.REMINDER,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["id"],
        "optional_args": [
            "title", "body", "due_at", "location_name", "latitude", "longitude", "radius_m",
            "activity", "status", "one_shot", "last_fired_at",
        ],
        "description": "Update an existing reminder",
    },
    "update_reminder_by_title": {
        "entity": CRUDEntity.REMINDER,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["title_match"],
        "optional_args": [
            "title", "body", "due_at", "location_name", "latitude", "longitude", "radius_m",
            "activity", "status", "one_shot", "last_fired_at",
        ],
        "description": "Update the most relevant reminder whose title contains title_match",
    },
    "complete_reminder": {
        "entity": CRUDEntity.REMINDER,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["id"],
        "optional_args": [],
        "description": "Mark a reminder completed",
    },
    "list_reminders": {
        "entity": CRUDEntity.REMINDER,
        "operation": CRUDOperation.LIST,
        "required_args": [],
        "optional_args": ["status"],
        "description": "List reminders, optionally filtered by status",
    },
    "delete_reminder": {
        "entity": CRUDEntity.REMINDER,
        "operation": CRUDOperation.DELETE,
        "required_args": ["id"],
        "optional_args": [],
        "description": "Delete one user-owned reminder",
    },
    "create_context_rule": {
        "entity": CRUDEntity.CONTEXT_RULE,
        "operation": CRUDOperation.CREATE,
        "required_args": ["name", "trigger_type", "trigger", "action_type", "action"],
        "optional_args": ["enabled", "one_shot"],
        "description": "Create a deterministic geofence, activity, or time rule that notifies, appends to a note, or updates a reminder",
    },
    "update_context_rule": {
        "entity": CRUDEntity.CONTEXT_RULE,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["id"],
        "optional_args": ["name", "trigger_type", "trigger", "action_type", "action", "enabled", "one_shot", "last_fired_at"],
        "description": "Update an existing context rule",
    },
    "list_context_rules": {
        "entity": CRUDEntity.CONTEXT_RULE,
        "operation": CRUDOperation.LIST,
        "required_args": [],
        "optional_args": ["enabled"],
        "description": "List local context rules",
    },
    "delete_context_rule": {
        "entity": CRUDEntity.CONTEXT_RULE,
        "operation": CRUDOperation.DELETE,
        "required_args": ["id"],
        "optional_args": [],
        "description": "Delete one user-owned deterministic context rule",
    },
    "list_notifications": {
        "entity": CRUDEntity.NOTIFICATION,
        "operation": CRUDOperation.LIST,
        "required_args": [],
        "optional_args": ["status"],
        "description": "List pending or delivered mobile notification outbox records",
    },
    "acknowledge_notification": {
        "entity": CRUDEntity.NOTIFICATION,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["id"],
        "optional_args": [],
        "description": "Mark a queued notification as delivered by the mobile client",
    },
    "save_place": {
        "entity": CRUDEntity.PLACE,
        "operation": CRUDOperation.CREATE,
        "required_args": ["name", "latitude", "longitude"],
        "optional_args": ["category", "notes", "tags"],
        "description": "Save a new place to the user's place library",
    },
    "get_session": {
        "entity": CRUDEntity.SESSION,
        "operation": CRUDOperation.READ,
        "required_args": ["id"],
        "optional_args": [],
        "description": "Get details of a mobility session",
    },
    "list_sessions": {
        "entity": CRUDEntity.SESSION,
        "operation": CRUDOperation.LIST,
        "required_args": [],
        "optional_args": ["status", "vehicle_class", "date_from", "date_to"],
        "description": "List mobility sessions with optional filters",
    },
    "update_preference": {
        "entity": CRUDEntity.PREFERENCE,
        "operation": CRUDOperation.UPDATE,
        "required_args": ["key", "value"],
        "optional_args": [],
        "description": "Update a user preference",
    },
    "create_automation": {
        "entity": CRUDEntity.AUTOMATION,
        "operation": CRUDOperation.CREATE,
        "required_args": ["trigger", "action"],
        "optional_args": ["conditions", "enabled"],
        "description": "Create an automation rule",
    },
    "log_event": {
        "entity": CRUDEntity.EVENT,
        "operation": CRUDOperation.CREATE,
        "required_args": ["event_type", "data"],
        "optional_args": ["source", "severity"],
        "description": "Log a context event",
    },
}


class FunctionRegistry:
    """
    Validates and executes allow-listed function calls.

    All function calls from Tier 2 must pass through this registry.
    Unauthorized or malformed calls are rejected with audit trail.
    """

    def __init__(self, crud_store: CRUDStore) -> None:
        self._crud = crud_store

    def validate(self, call: FunctionCall) -> FunctionCall:
        """
        Validate a function call against the allow-list and schema.
        Sets is_valid and validation_error on the FunctionCall.
        """
        # Check if function is in allow-list
        if call.function_name not in ALLOWED_FUNCTIONS:
            call.is_valid = False
            call.validation_error = (
                f"Function '{call.function_name}' is not in the allow-list. "
                f"Permitted functions: {list(ALLOWED_FUNCTIONS.keys())}"
            )
            return call

        spec = ALLOWED_FUNCTIONS[call.function_name]

        # Validate entity matches
        if call.entity != spec["entity"]:
            call.is_valid = False
            call.validation_error = (
                f"Entity mismatch: expected {spec['entity'].value}, got {call.entity.value}"
            )
            return call

        # Validate operation matches
        if call.operation != spec["operation"]:
            call.is_valid = False
            call.validation_error = (
                f"Operation mismatch: expected {spec['operation'].value}, got {call.operation.value}"
            )
            return call

        # Validate required arguments
        missing = [
            arg for arg in spec["required_args"]
            if arg not in call.arguments
        ]
        if missing:
            call.is_valid = False
            call.validation_error = f"Missing required arguments: {missing}"
            return call

        # Check for unknown arguments
        all_args = set(spec["required_args"] + spec["optional_args"])
        unknown = [arg for arg in call.arguments if arg not in all_args]
        if unknown:
            call.is_valid = False
            call.validation_error = f"Unknown arguments: {unknown}"
            return call

        call.is_valid = True
        call.validation_error = None
        return call

    def execute(self, call: FunctionCall) -> dict[str, Any]:
        """
        Execute a validated function call against the CRUD store.
        Returns the execution result.
        """
        if not call.is_valid:
            return {
                "success": False,
                "error": call.validation_error or "Call not validated",
            }

        spec = ALLOWED_FUNCTIONS[call.function_name]
        entity = spec["entity"]
        operation = spec["operation"]

        try:
            if operation == CRUDOperation.CREATE:
                record = self._crud.create(entity, call.arguments)
                return {"success": True, "record": record}

            elif operation == CRUDOperation.READ:
                record_id = call.arguments.get("id", "")
                record = self._crud.read(entity, record_id)
                if record:
                    return {"success": True, "record": record}
                return {"success": False, "error": f"Record {record_id} not found"}

            elif operation == CRUDOperation.UPDATE:
                record_id = call.arguments.get("id", "")
                update_data = {k: v for k, v in call.arguments.items() if k != "id"}
                record = self._crud.update(entity, record_id, update_data)
                if record:
                    return {"success": True, "record": record}
                return {"success": False, "error": f"Record {record_id} not found"}

            elif operation == CRUDOperation.DELETE:
                record_id = call.arguments.get("id", "")
                deleted = self._crud.delete(entity, record_id)
                return {"success": deleted, "error": None if deleted else "Not found"}

            elif operation == CRUDOperation.LIST:
                filters = {k: v for k, v in call.arguments.items()
                           if k in (spec.get("optional_args", []))}
                records = self._crud.list_all(entity, filters if filters else None)
                return {"success": True, "records": records, "count": len(records)}

            return {"success": False, "error": "Unknown operation"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_function_specs(self) -> dict[str, dict[str, Any]]:
        """Return the full function spec registry (for Tier 2 prompt construction)."""
        return ALLOWED_FUNCTIONS.copy()

    def is_allowed(self, function_name: str) -> bool:
        """Check if a function name is in the allow-list."""
        return function_name in ALLOWED_FUNCTIONS
