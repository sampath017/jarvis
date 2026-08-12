"""Single execution path for allow-listed assistant tools."""

from __future__ import annotations

from typing import Any

from ..cloud.function_registry import FunctionRegistry
from ..models.enums import CRUDEntity, CRUDOperation
from ..models.schemas import FunctionCall
from ..services.database import DatabaseService


_TABLE_BY_ENTITY = {
    CRUDEntity.TASK: "tasks",
    CRUDEntity.NOTE: "notes",
    CRUDEntity.PLACE: "places",
    CRUDEntity.SESSION: "mobilitySessions",
    CRUDEntity.PREFERENCE: "preferences",
    CRUDEntity.AUTOMATION: "automations",
    CRUDEntity.EVENT: "contextEvents",
}


class ActionService:
    """Validate and execute only the registered actions for one local user."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()
        self.registry = FunctionRegistry(None)  # type: ignore[arg-type]

    def execute(self, uid: str, call: FunctionCall) -> dict[str, Any]:
        self.registry.validate(call)
        if not call.is_valid:
            return {"success": False, "error": call.validation_error}

        try:
            result = self._execute_validated(uid, call)
            return {"success": True, "record": result}
        except LookupError as error:
            return {"success": False, "error": str(error)}
        except Exception as error:
            return {"success": False, "error": str(error)}

    def _execute_validated(self, uid: str, call: FunctionCall) -> dict[str, Any]:
        args = call.arguments
        name = call.function_name

        if name == "create_reminder":
            return self.db.create_reminder(uid, args)
        if name == "update_reminder":
            record = self.db.update_reminder(uid, args["id"], _without_id(args))
            return _require_record(record, args["id"])
        if name == "update_reminder_by_title":
            target = self.db.find_reminder_by_title(uid, args["title_match"])
            if not target:
                raise LookupError(f"Reminder matching {args['title_match']!r} not found")
            record = self.db.update_reminder(uid, target["id"], _without_title_match(args))
            return _require_record(record, target["id"])
        if name == "complete_reminder":
            record = self.db.complete_reminder(uid, args["id"])
            return _require_record(record, args["id"])
        if name == "list_reminders":
            return {"records": self.db.list_reminders(uid, status=args.get("status"))}
        if name == "delete_reminder":
            if not self.db.delete_reminder(uid, args["id"]):
                raise LookupError(f"Record {args['id']} not found")
            return {"id": args["id"], "deleted": True}

        if name == "create_context_rule":
            return self.db.create_context_rule(uid, args)
        if name == "update_context_rule":
            record = self.db.update_context_rule(uid, args["id"], _without_id(args))
            return _require_record(record, args["id"])
        if name == "list_context_rules":
            enabled = args.get("enabled")
            return {"records": self.db.list_context_rules(uid, enabled=enabled)}
        if name == "delete_context_rule":
            if not self.db.delete_context_rule(uid, args["id"]):
                raise LookupError(f"Record {args['id']} not found")
            return {"id": args["id"], "deleted": True}

        if name == "list_notifications":
            return {"records": self.db.list_notifications(uid, status=args.get("status"))}
        if name == "acknowledge_notification":
            record = self.db.acknowledge_notification(uid, args["id"])
            return _require_record(record, args["id"])

        if name == "update_note_by_title":
            target = self.db.find_note_by_title(uid, args["title_match"])
            if not target:
                raise LookupError(f"Note matching {args['title_match']!r} not found")
            record = self.db.update_note(uid, target["id"], _without_title_match(args))
            return _require_record(record, target["id"])

        table = _TABLE_BY_ENTITY.get(call.entity)
        if not table:
            raise ValueError(f"Unsupported entity {call.entity.value}")
        if call.operation == CRUDOperation.CREATE:
            return self.db.crud_create(uid, table, args)
        if call.operation == CRUDOperation.READ:
            return _require_record(self.db.crud_get(uid, table, args.get("id", "")), args.get("id", ""))
        if call.operation == CRUDOperation.UPDATE:
            record_id = args.get("id") or args.get("key")
            if not record_id:
                raise ValueError("Missing record ID or key for update")
            return _require_record(self.db.crud_update(uid, table, record_id, _without_id(args)), record_id)
        if call.operation == CRUDOperation.DELETE:
            deleted = self.db.crud_delete(uid, table, args.get("id", ""))
            if not deleted:
                raise LookupError(f"Record {args.get('id', '')} not found")
            return {"id": args.get("id"), "deleted": True}
        if call.operation == CRUDOperation.LIST:
            return {"records": self.db.crud_list(uid, table)}
        raise ValueError(f"Unsupported operation {call.operation.value}")


def _without_id(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key not in ("id", "key")}


def _without_title_match(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key != "title_match"}


def _require_record(record: dict[str, Any] | None, record_id: str) -> dict[str, Any]:
    if record is None:
        raise LookupError(f"Record {record_id} not found")
    return record
