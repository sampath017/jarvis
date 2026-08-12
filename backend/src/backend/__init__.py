"""Backend — session management, conflict resolution, audit logging, CRUD, and logging config."""

from .logging_config import configure_logging

__all__ = ["configure_logging"]
