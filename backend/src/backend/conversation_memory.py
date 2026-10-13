"""Bound recent dialogue without upgrading recalled assistant text to verified facts."""


def recent_history(messages, max_messages=24, max_chars=16000):
    selected = []
    remaining = max_chars
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        role = str(item.get('role', '')).lower()
        content = item.get('content') or item.get('text') or ''
        if (role not in {'user', 'human', 'assistant', 'ai', 'bot'}
                or not isinstance(content, str) or not content.strip()
                or str(item.get('id', '')).startswith('err_')
                or content.startswith('Added to Jarvis Upload Cache:')):
            continue
        if len(content) > remaining or len(selected) == max_messages:
            break
        selected.append({'role': role, 'content': content})
        remaining -= len(content)
    return list(reversed(selected))
