"""Device-executed Google Calendar tools. OAuth tokens never reach the agent."""
import json
from langchain_core.tools import tool
from ..backend.command_execution import execution


def calendar_tools():
    def dispatch(operation, **args):
        current = execution.get()
        if not current or not current.calendar_dispatch:
            return json.dumps({"status": "unavailable", "message": "Connect Google Calendar in Settings, then keep Jarvis open while using calendar commands."})
        current.check()
        return json.dumps(current.calendar_dispatch({"operation": operation, **args}))

    @tool
    def list_google_calendars() -> str:
        """List the connected Google account's calendars and access roles."""
        return dispatch("calendars")

    @tool
    def list_calendar_events(start_at: str, end_at: str, calendar_id: str = "", query: str = "", page_token: str = "") -> str:
        """Read Google events in an explicit ISO time window with timezone offsets.
        Instances of recurring events are returned. Follow nextPageToken if present.
        Use returned event IDs, never invent them. Empty calendar_id uses the user's default.
        """
        return dispatch("list", calendar_id=calendar_id, start_at=start_at, end_at=end_at, query=query, page_token=page_token)

    @tool
    def get_calendar_event(event_id: str, calendar_id: str = "") -> str:
        """Read a specific Google Calendar event using an ID from a previous search."""
        return dispatch("get", calendar_id=calendar_id, event_id=event_id)

    @tool
    def create_calendar_event(event: dict, calendar_id: str = "") -> str:
        """Propose creating a Google Calendar event; the phone MUST obtain approval.
        event uses Google event fields: summary, description, location, start, end,
        attendees (email objects), recurrence (RRULE strings). Timed start/end use
        {dateTime: ISO timestamp with offset, timeZone: IANA zone}. All-day use
        {date: YYYY-MM-DD}; end is exclusive. Invitations are sent only after approval.
        A declined proposal is NOT executed. Never claim success without status=ok.
        """
        return dispatch("create", calendar_id=calendar_id, event=event)

    @tool
    def update_calendar_event(event_id: str, changes: dict, calendar_id: str = "", whole_series: bool = False) -> str:
        """Propose editing a Google Calendar event, requiring approval on the phone.
        Search first and clarify ambiguous matches. changes contains only fields to
        change, using Google's event format. whole_series=true ONLY if the user
        explicitly requested the whole recurring series; otherwise use an instance ID.
        """
        return dispatch("update", calendar_id=calendar_id, event_id=event_id, event=changes, whole_series=whole_series)

    @tool
    def delete_calendar_event(event_id: str, calendar_id: str = "", whole_series: bool = False) -> str:
        """Propose deleting a Google Calendar event; requires approval on the phone.
        Search first. Ask which event if ambiguous. whole_series=true only when the
        user explicitly requested the entire recurring series; otherwise use an instance.
        Cancellation notices to guests must be disclosed in the approval preview.
        """
        return dispatch("delete", calendar_id=calendar_id, event_id=event_id, whole_series=whole_series)

    return [list_google_calendars, list_calendar_events, get_calendar_event,
            create_calendar_event, update_calendar_event, delete_calendar_event]
