"""Explicit, request-scoped reads from the authenticated phone."""
import json
import re
from datetime import date, datetime, timedelta, timezone

from langchain_core.tools import tool

from ..backend.command_execution import execution


def _window(start_date, end_date):
    end_date = end_date or start_date
    if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in (start_date, end_date)):
        raise ValueError('Use calendar dates in YYYY-MM-DD format, in Asia/Kolkata.')
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    if end < start or (end - start).days >= 31 or end > today:
        raise ValueError('Choose an inclusive window of 1 to 31 days, ending no later than today in Asia/Kolkata.')
    return end_date


def phone_data_tools():
    def read(operation, **arguments):
        try:
            arguments['end_date'] = _window(arguments['start_date'], arguments.get('end_date', ''))
        except ValueError as exc:
            return json.dumps({'status': 'invalid_arguments', 'message': str(exc)})
        current = execution.get()
        if not current or not current.approval_dispatch:
            return json.dumps({'status': 'unavailable', 'source': operation,
                'message': 'This data is on the phone. Keep Jarvis open with its device session connected, then retry. Do not substitute movement history or infer zero.'})
        current.check()
        result = current.approval_dispatch({'operation': operation, **arguments})
        current.check()
        return json.dumps(result, default=str, ensure_ascii=False)

    @tool
    def get_app_usage(start_date: str, end_date: str = '', app_query: str = '', max_apps: int = 20) -> str:
        """Read Android SCREEN TIME / APP USAGE / digital wellbeing for explicit calendar dates.
        Use for time spent in apps, usage breakdowns, yesterday's screen time, and app-usage charts.
        This is NOT movement/location history, steps or sleep. Resolve short follow-ups from the
        conversation's subject, date and chart type, then pass YYYY-MM-DD dates in Asia/Kolkata.
        end_date is inclusive, defaults to start_date, and the maximum window is 31 days.
        app_query optionally filters app names/packages. max_apps is 1..100; bounded results retain
        the remaining time in an aggregate. total_ms is the full day; matched_ms is filtered usage.
        Plot raw milliseconds converted to seconds/minutes, never rounded prose. Missing records
        or denied Usage Access are unknown, not zero. Reads do not grant OS permissions.
        """
        if not 1 <= max_apps <= 100 or len(app_query) > 120:
            return json.dumps({'status': 'invalid_arguments', 'message': 'Use max_apps between 1 and 100 and an app_query of at most 120 characters.'})
        return read('app_usage_read', start_date=start_date, end_date=end_date,
                    app_query=app_query, max_apps=max_apps)

    @tool
    def get_health_records(metric: str, start_date: str, end_date: str = '') -> str:
        """Read Health Connect STEPS or SLEEP sessions from the phone for calendar dates.
        metric must be steps or sleep. Dates are YYYY-MM-DD in Asia/Kolkata, inclusive, at most
        31 days. For steps a date means midnight to midnight (today ends now). For sleep a date
        means the night ending on that date: previous day 18:00 to that date 18:00, capped at now.
        Use for step counts and recorded sleep; Android app usage and movement history are
        different sources. SLEEP_SESSION time is recorded session time, not a medical measure
        of actual sleep. Never infer sleep from an idle phone or steps from movement duration.
        Existing Health Connect permissions are required; missing data is unknown, not zero.
        """
        if metric not in {'steps', 'sleep'}:
            return json.dumps({'status': 'invalid_arguments', 'message': 'metric must be steps or sleep.'})
        return read('health_records_read', metric=metric, start_date=start_date, end_date=end_date)

    return [get_app_usage, get_health_records]
