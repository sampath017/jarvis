"""Keep reminder validation separate from authorization and model guesses."""
import json
import re


def reminder_edit_requested(request: dict) -> bool:
    """Prevent a model from turning a policy edit into deletion + recreation.

    This guard blocks deletion only; it never invents an update or treats text
    as approval. Explicit deletion still uses the normal human approval path.
    """
    current = str(request.get('text') or '').lower()
    deletion = re.search(r'\b(?:delete|trash|remove|cancel)\b(.{0,50}?)\b(?:reminders?|policies|policy|rules?|it|them)\b', current)
    if deletion and not re.search(r'\b(?:condition|trigger|shop|movement|destination|requirement)\b', deletion.group(1)):
        return False
    recent = [str(m.get('content') or '') for m in request.get('history', [])[-12:]
              if isinstance(m, dict) and m.get('role') == 'user'][-3:]
    text = '\n'.join([*recent, current]).lower()
    return bool(re.search(r'\b(?:edit|update|change|modify|simplify|instead)\b|\b(?:remove|drop|without|no)\b.{0,35}\b(?:condition|trigger|shop|destination|movement)\b|\bshop.{0,25}\bor not\b', text))


def reminder_input_error(code: str, field: str, message: str) -> str:
    return json.dumps({
        'status': 'invalid_arguments', 'code': code, 'field': field,
        'message': message, 'saved': False, 'requires_approval': False,
        'recovery': 'Correct the tool arguments using the user request and conversation. '
                    'Ask a specific question only if the user did not provide the missing detail. '
                    'A yes/no confirmation does not fix invalid arguments. Do not repeat unchanged arguments.',
    })


_RELATIVE_CALL = re.compile(
    r'\s*(?:please\s+)?(?:call me|ring me|give me a call)\s+(?:in|after)\s+'
    r'(?:(?:the\s+)?next\s+)?(\d+)\s*'
    r'(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)'
    r'(?:\s+please)?[.!]?\s*', re.IGNORECASE,
)


def ground_relative_call(text: str, arguments: dict) -> dict:
    """Ground only a complete, unambiguous self-call request; never mixed tasks.

    Interpretation of general reminders remains with the agent. This narrow
    contract keeps a model from omitting a delay that the user explicitly gave,
    adding a location condition, or changing ringing delivery to notification.
    """
    match = _RELATIVE_CALL.fullmatch(text)
    if not match:
        return arguments
    count, unit = int(match[1]), match[2].lower()[0]
    seconds = count * {'s': 1, 'm': 60, 'h': 3600}[unit]
    if not 0 < seconds <= 30 * 86400:
        return arguments
    return {
        'title': arguments.get('title') or 'Call reminder',
        'due_at': f'in {seconds} seconds', 'delivery_mode': 'in_app_call',
    }


def outcome(result: str) -> tuple[str, str]:
    """Classify returned failures as failures even when the tool did not raise."""
    try:
        data = json.loads(result)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict) and data.get('status') in {
        'invalid_arguments', 'error', 'failed', 'not_executed', 'declined',
    }:
        return str(data['status']), str(data.get('code') or data['status'])
    lower = result.lstrip().lower()
    if lower.startswith('confirmation_required:'):
        return 'invalid_arguments', 'legacy_validation_error'
    if lower.startswith(('error', 'not saved:', 'not changed:', 'not executed:', 'not merged:')):
        return 'failed', 'tool_failed'
    return 'success', 'ok'


def repeated_reminder_failure(name: str, result: str) -> str:
    try:
        data = json.loads(result)
    except (ValueError, TypeError):
        data = {}
    message = data.get('message') if isinstance(data, dict) else None
    if not message:
        message = 'The reminder tool could not apply the supplied details.'
    action = 'save' if name == 'create_reminder' else 'update'
    return f'I couldn\'t {action} that reminder: {message} This reminder operation did not complete.'
