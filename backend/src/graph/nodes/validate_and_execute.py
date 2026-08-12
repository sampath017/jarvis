"""
Validate and Execute node — validate tool calls and write to local database.

Class-based node implementation for validating tool calls and executing CRUD on native SQL tables.
Integrated with AuditLog for execution logging.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ..state import JarvisState
from ...cloud.function_registry import FunctionRegistry
from ...models.schemas import FunctionCall
from ...models.enums import CRUDEntity, CRUDOperation
from ...services.database import DatabaseService
from ...backend.audit_log import audit_from_state
from ...backend.action_service import ActionService

logger = logging.getLogger(__name__)

# Map CRUDEntity to SQL table names
TABLE_MAP = {
    CRUDEntity.TASK: "tasks",
    CRUDEntity.NOTE: "notes",
    CRUDEntity.PLACE: "places",
    CRUDEntity.SESSION: "mobilitySessions",
    CRUDEntity.PREFERENCE: "preferences",
    CRUDEntity.AUTOMATION: "automations",
    CRUDEntity.EVENT: "contextEvents",
}


class ValidateAndExecuteNode:
    """Class-based node handler to validate tool calls and execute CRUD on the local database."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()

    def __call__(self, state: JarvisState) -> dict:
        """Validate proposed function calls and execute them."""
        tool_calls = state.get("tool_calls", [])
        uid = state.get("uid", "")
        event_id = state.get("event_id", "")
        audit = audit_from_state(state, self.db)

        if not tool_calls:
            return {"tool_results": [], "changed_records": []}

        if not uid:
            audit.log(
                node_name="validate_and_execute",
                action="missing_uid",
                category="CRUD",
                event_id=event_id,
                execution_result="error",
                error_detail="Missing user ID for tool execution",
            )
            return {"error": "Missing user ID for tool execution", "tool_results": []}

        executor = ActionService(self.db)
        results = []
        changed_ids = []

        for call_dict in tool_calls:
            try:
                call = FunctionCall(
                    function_name=call_dict.get("function_name", ""),
                    entity=CRUDEntity(call_dict.get("entity")),
                    operation=CRUDOperation(call_dict.get("operation")),
                    arguments=call_dict.get("arguments", {}),
                )
            except (AttributeError, TypeError, ValueError) as error:
                function_name = str(call_dict.get("function_name", "")) if isinstance(call_dict, dict) else ""
                results.append({"function_name": function_name, "success": False, "error": str(error)})
                audit.log(
                    node_name="validate_and_execute",
                    action=f"rejected:{function_name or 'malformed'}",
                    category="CRUD",
                    event_id=event_id,
                    input_summary={"call": call_dict if isinstance(call_dict, dict) else {}},
                    execution_result="rejected",
                    error_detail=str(error),
                )
                continue

            executor.registry.validate(call)

            if not call.is_valid:
                logger.warning("Rejected invalid function call: %s", call.validation_error)
                results.append({
                    "function_name": call.function_name,
                    "success": False,
                    "error": call.validation_error,
                })
                audit.log(
                    node_name="validate_and_execute",
                    action=f"rejected:{call.function_name}",
                    category="CRUD",
                    event_id=event_id,
                    input_summary={
                        "function_name": call.function_name,
                        "entity": call.entity.value,
                        "operation": call.operation.value,
                        "arguments": call.arguments,
                    },
                    execution_result="rejected",
                    error_detail=call.validation_error,
                )
                continue

            try:
                exec_res = executor.execute(uid, call)
                results.append(exec_res)

                if exec_res.get("success"):
                    record = exec_res.get("record", {})
                    rec_id = record.get("id") or call.arguments.get("id")
                    if rec_id:
                        changed_ids.append(rec_id)

                    audit.log(
                        node_name="validate_and_execute",
                        action=f"executed:{call.function_name}",
                        category="CRUD",
                        event_id=event_id,
                        input_summary={
                            "function_name": call.function_name,
                            "entity": call.entity.value,
                            "operation": call.operation.value,
                            "arguments": call.arguments,
                        },
                        output_summary={
                            "record_id": rec_id,
                            "entity": call.entity.value,
                        },
                    )
                else:
                    audit.log(
                        node_name="validate_and_execute",
                        action=f"failed:{call.function_name}",
                        category="CRUD",
                        event_id=event_id,
                        input_summary={
                            "function_name": call.function_name,
                            "entity": call.entity.value,
                            "operation": call.operation.value,
                            "arguments": call.arguments,
                        },
                        execution_result="error",
                        error_detail=exec_res.get("error"),
                    )

            except Exception as e:
                logger.critical("Error executing tool %s: %s", call.function_name, e, exc_info=True)
                results.append({
                    "function_name": call.function_name,
                    "success": False,
                    "error": str(e),
                })
                audit.log(
                    node_name="validate_and_execute",
                    action=f"exception:{call.function_name}",
                    category="CRUD",
                    event_id=event_id,
                    input_summary={
                        "function_name": call.function_name,
                        "arguments": call.arguments,
                    },
                    execution_result="error",
                    error_detail=str(e),
                )

        return {
            "tool_results": results,
            "changed_records": changed_ids,
        }

    def _execute_crud(self, uid: str, table: str, call: FunctionCall) -> dict[str, Any]:
        """Execute a CRUD operation against the local database."""
        op = call.operation
        args = call.arguments

        if op == CRUDOperation.CREATE:
            record = self.db.crud_create(uid, table, args)
            return {"success": True, "record": record}

        elif op == CRUDOperation.READ:
            record_id = args.get("id", "")
            record = self.db.crud_get(uid, table, record_id)
            if record:
                return {"success": True, "record": record}
            return {"success": False, "error": f"Record {record_id} not found"}

        elif op == CRUDOperation.UPDATE:
            record_id = args.get("id") or args.get("key")
            if not record_id:
                return {"success": False, "error": "Missing record ID or key for update"}
            update_data = {k: v for k, v in args.items() if k not in ("id", "key")}
            record = self.db.crud_update(uid, table, record_id, update_data)
            if record:
                return {"success": True, "record": record}
            return {"success": False, "error": f"Record {record_id} not found"}

        elif op == CRUDOperation.DELETE:
            record_id = args.get("id", "")
            deleted = self.db.crud_delete(uid, table, record_id)
            return {"success": deleted, "error": None if deleted else "Not found"}

        elif op == CRUDOperation.LIST:
            records = self.db.crud_list(uid, table)
            return {"success": True, "record": {"records": records}}

        return {"success": False, "error": "Unknown operation type"}


# Callable instance for graph composition
validate_and_execute = ValidateAndExecuteNode()
