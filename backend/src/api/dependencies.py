"""FastAPI Dependency Injection definitions."""

from functools import lru_cache
from ..graph.builder import build_workflow


@lru_cache
def get_workflow():
    """Dependency returning the compiled LangGraph workflow app singleton."""
    return build_workflow()
