"""
FastAPI Dependency Injection definitions.
"""

from __future__ import annotations

from ..graph.builder import build_workflow

# Singleton workflow graph instance
_workflow_app = None


def get_workflow():
    """Dependency returning the compiled LangGraph workflow app singleton."""
    global _workflow_app
    if _workflow_app is None:
        _workflow_app = build_workflow()
    return _workflow_app
