"""
Repository Mixins for DatabaseService domain models.
"""

from .tasks_repo import TasksRepositoryMixin
from .notes_repo import NotesRepositoryMixin
from .places_repo import PlacesRepositoryMixin
from .preferences_repo import PreferencesRepositoryMixin
from .automations_repo import AutomationsRepositoryMixin
from .reminders_repo import RemindersRepositoryMixin
from .context_rules_repo import ContextRulesRepositoryMixin
from .notifications_repo import NotificationsRepositoryMixin
from .sessions_repo import SessionsRepositoryMixin
from .events_repo import EventsRepositoryMixin
from .chat_repo import ChatRepositoryMixin
from .audit_repo import AuditRepositoryMixin

__all__ = [
    "TasksRepositoryMixin",
    "NotesRepositoryMixin",
    "PlacesRepositoryMixin",
    "PreferencesRepositoryMixin",
    "AutomationsRepositoryMixin",
    "RemindersRepositoryMixin",
    "ContextRulesRepositoryMixin",
    "NotificationsRepositoryMixin",
    "SessionsRepositoryMixin",
    "EventsRepositoryMixin",
    "ChatRepositoryMixin",
    "AuditRepositoryMixin",
]
