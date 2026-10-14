"""Code-enforced capabilities and bounds for each agent invocation."""
import time

from .command_execution import CommandExecution, CommandStopped, execution

BACKGROUND_MAX_ITERATIONS = 4
BACKGROUND_MAX_TOOLS = 8
BACKGROUND_OUTPUT_TOKENS = 2048
BACKGROUND_MAX_SECONDS = 90


def background_invocation(state):
    return state.get("request_type") == "CONTEXT_EVENT"


def check_background_deadline(state):
    context = execution.get()
    if context:
        context.check()
    else:
        CommandExecution(publish=lambda _: None).check()
    started = state.get("agent_started_at", time.monotonic())
    if time.monotonic() - started >= BACKGROUND_MAX_SECONDS:
        raise CommandStopped("Background context assessment exceeded its time budget.")
