"""Execution-scoped proof of a device approval, never a model tool argument."""
from contextvars import ContextVar
import json

approved_tool_call: ContextVar[str | None] = ContextVar('approved_tool_call', default=None)


def approval_key(name: str, arguments: dict) -> str:
    return name + ':' + json.dumps(arguments, sort_keys=True, default=str)


def require_tool_approval(name: str, arguments: dict) -> None:
    if approved_tool_call.get() != approval_key(name, arguments):
        raise PermissionError('Not executed: deletion requires approval in the Jarvis app.')
