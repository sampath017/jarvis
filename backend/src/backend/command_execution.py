"""Public progress and cooperative safety limits for a single command.

Progress describes application operations only; no model reasoning is exposed.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import time
from typing import Callable

MAX_COMMAND_SECONDS = 600
MAX_COMMAND_ROUNDS = 24
MAX_COMMAND_TOOLS = 48

class CommandStopped(RuntimeError):
    pass

@dataclass
class CommandExecution:
    publish: Callable[[str], None]
    cancelled: Callable[[], bool] = lambda: False
    started: float = field(default_factory=time.monotonic)
    rounds: int = 0
    tools: int = 0
    repeated: dict[str, int] = field(default_factory=dict)
    writes: dict[str, str] = field(default_factory=dict)
    changed_records: list[str] = field(default_factory=list)

    def check(self):
        if self.cancelled():
            raise CommandStopped('Stopped at your request. Any actions already completed are still saved.')
        if time.monotonic() - self.started >= MAX_COMMAND_SECONDS:
            raise CommandStopped('Stopped safely after 10 minutes. Any completed actions are saved; please check them before trying again.')

    def report(self, message: str):
        self.check()
        self.publish(message)

    def model_turn(self):
        self.check()
        self.rounds += 1
        if self.rounds > MAX_COMMAND_ROUNDS:
            raise CommandStopped('Stopped safely because the request needed too many processing rounds. Any completed actions are saved.')

    def tool_key(self, name, args):
        self.check()
        self.tools += 1
        if self.tools > MAX_COMMAND_TOOLS:
            raise CommandStopped('Stopped safely after too many actions. Any completed actions are saved.')
        key = name + ':' + json.dumps(args, sort_keys=True, default=str)
        self.repeated[key] = self.repeated.get(key, 0) + 1
        if self.repeated[key] > 3:
            raise CommandStopped('Stopped safely because the same step kept repeating. Any completed actions are saved.')
        return key

execution: ContextVar[CommandExecution | None] = ContextVar('command_execution', default=None)

def report_progress(message):
    current = execution.get()
    if current:
        current.report(message)

NODE_LABELS = {
    'verify': 'Reading your request',
    'load_context': 'Checking your recent context',
    'intent_router': 'Preparing your request',
    'tier2_agent': 'Working through your request',
    'persist': 'Saving your response',
}

def observed_node(name, handler):
    def invoke(state):
        if state.get('request_type') == 'USER_COMMAND':
            report_progress(NODE_LABELS.get(name, 'Checking context'))
        return handler(state)
    return invoke

TOOL_LABELS = {
    'get_current_location': 'Checking your location',
    'list_saved_places': 'Checking your saved places',
    'search_nearby_places': 'Looking up nearby places',
    'inspect_satellite_view': 'Checking the map',
    'recall_context_history': 'Reading your activity history',
    'create_reminder': 'Saving your reminder',
    'update_reminder': 'Updating your reminder',
    'consolidate_reminders': 'Reviewing your reminders',
    'list_reminders': 'Checking your reminders',
    'search_reminders': 'Finding the matching reminder',
    'delete_reminder': 'Moving the reminder to Trash',
    'delete_all_reminders': 'Moving reminders to Trash',
    'restore_reminder': 'Restoring your reminder',
    'create_note': 'Saving your note',
    'list_notes': 'Reading your notes',
    'search_notes': 'Finding your note',
    'delete_note': 'Moving the note to Trash',
    'delete_all_notes': 'Moving notes to Trash',
    'restore_note': 'Restoring your note',
    'create_task': 'Saving your task',
    'list_tasks': 'Checking your tasks',
    'update_task': 'Updating your task',
    'update_task_status': 'Updating your task',
    'delete_task': 'Deleting your task',
    'save_place': 'Saving your place',
    'delete_place': 'Deleting your saved place',
}
