"""Real SQLite backing for the native method-channel regression tests."""
import json
import sqlite3
import sys

db = sqlite3.connect(':memory:', isolation_level=None)
db.row_factory = sqlite3.Row

def execute(value):
    cursor = db.execute(value['sql'], value.get('arguments') or [])
    if value.get('method') == 'query':
        return [dict(row) for row in cursor.fetchall()]
    if value.get('method') == 'insert':
        return cursor.lastrowid
    return cursor.rowcount

for line in sys.stdin:
    try:
        value = json.loads(line)
        if value['method'] == 'batch':
            result = [{'result': execute(op)} for op in value['operations']]
        else:
            result = execute(value)
        print(json.dumps({'result': result}), flush=True)
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), flush=True)
