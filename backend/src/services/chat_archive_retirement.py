"""Retire only verified message copies, with transactional concurrency guards."""
from datetime import datetime, timezone
import json

from fastapi import HTTPException
from src.services import sqlite_documents as documents

from .sync_change_feed import SyncChangeFeed
from .chat_message_time import message_stamp


def comparable(message, *, mobile=False):
    at = message_stamp(message['timestamp'], message_id=message.get('id'),
                       role=('user' if message['is_user'] else 'assistant') if mobile else message.get('role', 'user'))
    executed = message.get('executed_records') or []
    if isinstance(executed, str):
        executed = json.loads(executed)
    return (message['text'] if mobile else message.get('content', ''),
            message['is_user'] if mobile else message.get('role', 'user') == 'user',
            at, tuple(executed),
            message.get('run_id'), message.get('duration_ms'))


def retire(db, uid, thread_id, archive, file_id, digest, connection, email, *, guard=None, reason='manual'):
    messages = {m.id: m.model_dump(mode='json') for m in archive.session.messages}
    if len(messages) != len(archive.session.messages) or archive.session.id != thread_id:
        raise HTTPException(422, 'Backup contains duplicate IDs or a different conversation')
    ref = db.collection('chat_sessions').document(thread_id)
    query = db.collection('chat_messages').where('thread_id', '==', thread_id).limit(400)

    @documents.transactional
    def commit(tx):
        current = ref.get(transaction=tx).to_dict() or {}
        if current.get('uid') != uid:
            raise HTTPException(404, 'Conversation not found')
        if guard:
            guard(tx, current)
        rows = list(query.stream(transaction=tx))
        for row in rows:
            value = row.to_dict()
            saved = messages.get(row.id)
            try:
                equal = saved is not None and comparable(value) == comparable(saved, mobile=True)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise HTTPException(409, 'A saved message has an invalid timestamp. Cloud messages were kept; refresh the chat before retrying.') from exc
            if value.get('uid') != uid or not equal:
                raise HTTPException(409, 'The conversation changed or the backup is incomplete. Sync and retry; cloud messages were kept')
        patched = {**current, 'archive_drive_id': file_id, 'archive_sha256': digest,
                   'archive_connection': connection, 'archive_account': email,
                   'archive_message_count': len(messages), 'archived_at': datetime.now(timezone.utc).isoformat(),
                   'archive_reason': reason, 'archive_pending': len(rows) >= 400}
        SyncChangeFeed(db).append(tx, uid, 'chat_sessions', thread_id, patched)
        tx.set(ref, patched)
        for row in rows:
            tx.delete(row.reference)
        return {'archived': True, 'cloud_messages_removed': len(rows), 'message_count': len(messages),
                'file_id': file_id, 'sha256': digest}

    removed = 0
    for _ in range(len(messages) // 400 + 2):
        result = commit(db.transaction())
        removed += result['cloud_messages_removed']
        if result['cloud_messages_removed'] < 400:
            return {**result, 'cloud_messages_removed': removed}
    raise HTTPException(409, 'The conversation changed while archiving. Sync and retry.')
