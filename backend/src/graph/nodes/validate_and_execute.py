"""
Validate and Execute node — validate tool calls and write to Firestore.

Class-based node implementation for validating tool calls and writing changes to Firestore.
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
from ...services.firestore_client import FirestoreService
from ...backend.audit_log import AuditLog

logger = logging.getLogger(__name__)

# Map CRUDEntity to Firestore collection names
COLLECTION_MAP = {
    CRUDEntity.TASK: "tasks",
    CRUDEntity.NOTE: "notes",
    CRUDEntity.PLACE: "places",
    CRUDEntity.SESSION: "mobilitySessions",
    CRUDEntity.PREFERENCE: "preferences",
    CRUDEntity.AUTOMATION: "automations",
    CRUDEntity.EVENT: "contextEvents",
}


class ValidateAndExecuteNode:
    """Class-based node handler to validate tool call schemas and execute on Firestore."""

    def __init__(self, firestore_service: FirestoreService | None = None) -> None:
        self.firestore_service = firestore_service or FirestoreService()

    def __call__(self, state: JarvisState) -> dict:
        """Validate proposed function calls and execute them on Firestore."""
        tool_calls = state.get("tool_calls", [])
        uid = state.get("uid", "")
        event_id = state.get("event_id", "")

        if not tool_calls:
            return {"tool_results": [], "changed_records": []}

        if not uid:
            return {"error": "Missing user ID for tool execution", "tool_results": []}

        fs = self.firestore_service
        registry = FunctionRegistry(None)  # type: ignore[arg-type]
        results = []
        changed_ids = []
        audit = AuditLog()

        for call_dict in tool_calls:
            # Reconstruct FunctionCall schema
            call = FunctionCall(
                function_name=call_dict.get("function_name", ""),
                entity=CRUDEntity(call_dict.get("entity")),
                operation=CRUDOperation(call_dict.get("operation")),
                arguments=call_dict.get("arguments", {}),
            )

            # Validate call schema
            registry.validate(call)

            if not call.is_valid:
                logger.warning("Rejected invalid function call: %s", call.validation_error)
                results.append({
                    "function_name": call.function_name,
                    "success": False,
                    "error": call.validation_error,
                })
                audit.log(
                    event_id=event_id,
                    component="function_registry",
                    action=f"REJECTED: {call.function_name}",
                    input_ref={"function": call.function_name, "args": call.arguments},
                    output={},
                    execution_result="rejected",
                    error_detail=call.validation_error,
                )
                continue

            # Execute on Firestore
            collection = COLLECTION_MAP.get(call.entity)
            if not collection:
                results.append({
                    "function_name": call.function_name,
                    "success": False,
                    "error": f"Unsupported entity {call.entity}",
                })
                continue

            try:
                exec_res = _execute_firestore_op(fs, uid, collection, call)
                results.append(exec_res)

                if exec_res.get("success"):
                    record = exec_res.get("record", {})
                    rec_id = record.get("id") or call.arguments.get("id")
                    if rec_id:
                        changed_ids.append(rec_id)

                    audit.log(
                        event_id=event_id,
                        component="function_registry",
                        action=f"Executed: {call.function_name}",
                        input_ref={"function": call.function_name, "args": call.arguments},
                        output={"record_id": rec_id},
                        execution_result="success",
                    )
                else:
                    audit.log(
                        event_id=event_id,
                        component="function_registry",
                        action=f"FAILED: {call.function_name}",
                        input_ref={"function": call.function_name, "args": call.arguments},
                        output={},
                        execution_result="error",
                        error_detail=exec_res.get("error"),
                    )

            except Exception as e:
                logger.error("Error executing tool %s: %s", call.function_name, e)
                results.append({
                    "function_name": call.function_name,
                    "success": False,
                    "error": str(e),
                })

        return {
            "tool_results": results,
            "changed_records": changed_ids,
            "audit_entries": audit.to_dicts(),
        }


def _execute_firestore_op(
    fs: FirestoreService,
    uid: str,
    collection: str,
    call: FunctionCall,
) -> dict[str, Any]:
    """Execute standard CRUD operation against Firestore collections."""
    op = call.operation
    args = call.arguments

    if op == CRUDOperation.CREATE:
        doc_id = str(uuid.uuid4())
        record = fs.create_document(uid, collection, doc_id, args)
        return {"success": True, "record": record}

    elif op == CRUDOperation.READ:
        doc_id = args.get("id", "")
        record = fs.get_document(uid, collection, doc_id)
        if record:
            return {"success": True, "record": record}
        return {"success": False, "error": f"Record {doc_id} not found"}

    elif op == CRUDOperation.UPDATE:
        doc_id = args.get("id") or args.get("key")  # preferences use 'key'
        if not doc_id:
            return {"success": False, "error": "Missing document ID or key for update"}
        # Strip ID from data body
        update_data = {k: v for k, v in args.items() if k not in ("id", "key")}
        record = fs.update_document(uid, collection, doc_id, update_data)
        if record:
            return {"success": True, "record": record}
        return {"success": False, "error": f"Record {doc_id} not found"}

    elif op == CRUDOperation.DELETE:
        doc_id = args.get("id", "")
        deleted = fs.delete_document(uid, collection, doc_id)
        return {"success": deleted, "error": None if deleted else "Not found"}

    elif op == CRUDOperation.LIST:
        records = fs.list_documents(uid, collection, filters=args)
        return {"success": True, "record": {"records": records}}

    return {"success": False, "error": "Unknown operation type"}


# Callable instance for graph composition
validate_and_execute = ValidateAndExecuteNode()
