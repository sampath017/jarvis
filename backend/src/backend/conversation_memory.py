"""Normalize the complete current dialogue without silently removing older turns."""
from datetime import datetime, timezone


def conversation_history(messages):
    selected = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get('role', '')).lower()
        content = item.get('content') or item.get('text') or ''
        if (role not in {'user', 'human', 'assistant', 'ai', 'bot'}
                or not isinstance(content, str) or not content.strip()
                or content.startswith('Added to Jarvis Upload Cache:')):
            continue
        message = {'role': role, 'content': content}
        if item.get('is_error') is True or str(item.get('id', '')).startswith('err_'):
            message['is_error'] = True
        try:
            timestamp = datetime.fromisoformat(str(item.get('timestamp', '')).replace('Z', '+00:00'))
            if timestamp.tzinfo is not None:
                message['timestamp'] = timestamp.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
        selected.append(message)
    return selected
