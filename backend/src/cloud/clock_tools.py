"""Local-clock controls dispatched to the foreground phone, never server timers."""
import json
from langchain_core.tools import tool
from ..backend.command_execution import execution

ACTIONS = frozenset({
    'alarm.save', 'alarm.toggle', 'alarm.skip', 'delete', 'dismiss', 'snooze',
    'timer.pause', 'timer.resume', 'timer.reset', 'timer.add',
    'stopwatch.start', 'stopwatch.pause', 'stopwatch.reset', 'stopwatch.lap',
    'world.add', 'world.remove', 'bedtime.save',
})

def clock_tools():
    def dispatch(action, arguments):
        current = execution.get()
        if not current or not current.approval_dispatch:
            return json.dumps({'status':'unavailable','message':'Open Jarvis on your phone to control its local Clock. No timer or alarm was created.'})
        current.check()
        result = current.approval_dispatch({'operation':'clock_action','clock_action':action,'arguments':arguments})
        current.check()
        return json.dumps(result, ensure_ascii=False, default=str)

    @tool
    def get_clock() -> str:
        """Read Jarvis Clock alarms, timer IDs/remaining milliseconds, stopwatch and bedtime on the phone.
        This is a custom local Clock inside Jarvis, separate from reminders and Google Clock.
        Read IDs before editing/deleting existing timers or alarms; never guess them.
        """
        return dispatch('snapshot', {})

    @tool
    def create_clock_timer(seconds: int, label: str = 'Timer') -> str:
        """Start a named countdown in the phone's Jarvis Clock (1..31536000 seconds).
        Use for 'set a timer', cooking/focus countdowns and elapsed-time requests, not saved reminders.
        Android owns ringing even if Jarvis assistant is off. Report success only from an ok phone receipt.
        """
        if isinstance(seconds, bool) or not 1 <= seconds <= 31536000 or len(label) > 120:
            return json.dumps({'status':'invalid_arguments','message':'Use 1..31536000 seconds and a label of at most 120 characters.'})
        return dispatch('timer.start', {'seconds':seconds,'label':label})

    @tool
    def update_clock(action: str, arguments: dict) -> str:
        """Control the custom local Jarvis Clock. Read get_clock for IDs first.
        alarm.save: hour (0..23), minute (0..59), label, days (ISO weekdays Mon=1..Sun=7;
        empty for one-time), enabled, vibrate, optional existing id. Clock uses phone's local timezone.
        alarm.toggle: id, enabled; alarm.skip: id. timer.pause/resume/reset: id.
        timer.add: id, seconds (e.g. 60). dismiss/snooze: ringing item id. delete: exact item id.
        stopwatch.start/pause/reset/lap: empty arguments. world.add/remove: zone IANA identifier.
        bedtime.save: bedHour, bedMinute, wakeHour, wakeMinute, days, enabled.
        A one-time timer measures elapsed time, not a future wall-clock reminder or continuous activity.
        Do not change unrelated alarms, or claim success without an ok phone receipt.
        """
        if action not in ACTIONS or not isinstance(arguments, dict):
            return json.dumps({'status':'invalid_arguments','message':'Unsupported clock action.'})
        if any(k.startswith('__') for k in arguments):
            return json.dumps({'status':'invalid_arguments','message':'Reserved argument name.'})
        return dispatch(action, arguments)

    return [get_clock, create_clock_timer, update_clock]
