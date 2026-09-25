"""Durable background indexing, private resumable staging, no stored Drive tokens."""
import hashlib
import os
import secrets
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.cloud import firestore, storage
from .firestore_service import FirestoreService

PROJECT = 'jarvis-agent-61947'
REGION = 'asia-south1'
JOB = 'jarvis-drive-indexer'


def db():
    return FirestoreService()._db


def jobs():
    return db().collection('drive_index_jobs')


def bucket():
    return storage.Client(project=PROJECT).bucket(os.environ['INDEX_STAGING_BUCKET'])


def identity(owner, memory):
    return hashlib.sha256(f"{owner}:{memory['account']}:{memory['id']}:{memory.get('source_version', '')}".encode()).hexdigest()


def begin(owner, memory):
    job_id = identity(owner, memory)
    ref = jobs().document(job_id)
    record = ref.get().to_dict() or {}
    expected = {
        'application/vnd.google-apps.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.google-apps.spreadsheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.google-apps.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/vnd.google-apps.drawing': 'image/png',
    }.get(memory['mimeType'], memory['mimeType'])
    # Refresh older export formats through the owner's normal upload flow.
    # Claim transactions prevent a queued stale source being processed mid-upload.
    current = record.get('status') == 'processing' or (record.get('status') in ('queued', 'complete') and
        record.get('memory', {}).get('mimeType') == expected)
    if current:
        if record.get('status') != 'complete':
            kick()
        return {'job_id': job_id, 'upload_required': False, 'status': record['status']}
    object_name = f'sources/{owner}/{job_id}-{secrets.token_hex(8)}'
    ref.set({'owner': owner, 'memory': memory, 'object': object_name,
        'status': 'uploading', 'updated_at': datetime.now(timezone.utc)})
    session = bucket().blob(object_name).create_resumable_upload_session(content_type='application/octet-stream',
        size=None, timeout=30)
    return {'job_id': job_id, 'upload_required': True, 'upload_url': session}


def catalog(owner, memory, reason, needs_attention=True):
    from .file_readers import CATALOG_MIME
    job_id = identity(owner, memory)
    ref = jobs().document(job_id)
    previous = ref.get().to_dict() or {}
    if previous.get('source_reason') == reason and previous.get('status') in ('queued', 'processing', 'complete', 'attention'):
        if previous['status'] in ('queued', 'processing'):
            kick()
        return {'job_id': job_id, 'status': previous['status'], 'coverage': 'metadata', 'reason': reason}
    name = f'sources/{owner}/{job_id}-{secrets.token_hex(8)}'
    data = json.dumps({'memory': memory, 'reason': reason, 'needs_attention': needs_attention}, ensure_ascii=False).encode()
    bucket().blob(name).upload_from_string(data, content_type=CATALOG_MIME)
    ref.set({'owner': owner, 'memory': {**memory, 'mimeType': CATALOG_MIME}, 'object': name,
        'status': 'queued', 'source_reason': reason, 'attention_required': needs_attention, 'updated_at': datetime.now(timezone.utc)})
    kick()
    return {'job_id': job_id, 'status': 'queued', 'coverage': 'metadata', 'reason': reason}


def finish(owner, job_id, size, mime):
    ref = jobs().document(job_id)
    value = ref.get().to_dict() or {}
    if value.get('owner') != owner:
        raise ValueError('Index upload not found')
    blob = bucket().blob(value['object'])
    blob.reload()
    if blob.size != size or size <= 0:
        raise ValueError('Uploaded size does not match')
    memory = {**value['memory'], 'size': size, 'mimeType': mime}
    ref.update({'memory': memory, 'status': 'queued', 'updated_at': datetime.now(timezone.utc)})
    kick()
    return {'job_id': job_id, 'status': 'queued'}


def kick():
    """Reserve one drain execution across all backend instances."""
    lease = db().collection('drive_index_control').document('worker')
    nonce = secrets.token_hex(16)
    now = datetime.now(timezone.utc)

    @firestore.transactional
    def reserve(transaction):
        value = lease.get(transaction=transaction).to_dict() or {}
        if value.get('expires_at', now) > now:
            return False
        transaction.set(lease, {'nonce': nonce, 'expires_at': now + timedelta(minutes=15)})
        return True
    if not reserve(db().transaction()):
        return
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        response = AuthorizedSession(credentials).post(
            f'https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{JOB}:run',
            json={'overrides': {'containerOverrides': [{'env': [{'name': 'DRAIN_NONCE', 'value': nonce}]}]}}, timeout=30)
        response.raise_for_status()
    except Exception:
        lease.set({'nonce': nonce, 'expires_at': now})
        raise


def status(owner):
    counts = {}
    query = jobs().where(filter=firestore.FieldFilter('owner', '==', owner))
    for state in ('uploading', 'queued', 'processing', 'complete', 'attention', 'failed'):
        counts[state] = query.where(filter=firestore.FieldFilter('status', '==', state)).count().get()[0][0].value
    records = [doc.to_dict() for doc in query.where(filter=firestore.FieldFilter('status', 'in', ['processing', 'attention', 'failed'])).limit(20).stream()]
    if counts.get('queued') or counts.get('processing'):
        kick()
    return {'counts': counts, 'files': [{ 'name': r['memory']['name'], 'status': r['status'],
        'chunks': r.get('chunks', 0), 'coverage': r.get('coverage', ''), 'issues': r.get('issues', {}),
        'error': r.get('error', '')} for r in records][:20]}


def results(owner, account, after=None):
    query = jobs().where(filter=firestore.FieldFilter('owner', '==', owner)).order_by('__name__')
    if after:
        cursor = jobs().document(after).get()
        if not cursor.exists or cursor.to_dict().get('owner') != owner:
            raise ValueError('Invalid results cursor')
        query = query.start_after(cursor)
    records = list(query.limit(100).stream())
    items = []
    for doc in records:
        r = doc.to_dict()
        if r['memory']['account'] != account:
            continue
        error = r.get('error', '')
        if '/sources/' in error or error.startswith('Command '):
            error = 'The file reader could not complete processing. Retry with the updated reader.'
        items.append({'id': doc.id, 'name': r['memory']['name'], 'status': r['status'],
            'coverage': r.get('coverage', 'content' if r['status'] == 'complete' else ''),
            'issues': r.get('issues', {}), 'error': error, 'chunks': r.get('chunks', 0)})
    return {'items': items, 'next_cursor': records[-1].id if len(records) == 100 else None}


def drain():
    from .drive_index import put_file
    nonce = os.environ['DRAIN_NONCE']
    lease = db().collection('drive_index_control').document('worker')
    current = lease.get().to_dict() or {}
    if current.get('nonce') != nonce:
        return

    def heartbeat(total=None, ref=None):
        lease.update({'expires_at': datetime.now(timezone.utc) + timedelta(minutes=15)})
        if ref is not None:
            ref.update({'chunks': total, 'updated_at': datetime.now(timezone.utc)})

    # An execution retry resumes its interrupted file before taking new files.
    for doc in jobs().where(filter=firestore.FieldFilter('status', '==', 'processing')).stream():
        if doc.to_dict().get('worker') == nonce:
            doc.reference.update({'status': 'queued'})
    while True:
        heartbeat()
        pending = list(jobs().where(filter=firestore.FieldFilter('status', '==', 'queued')).limit(1).stream())
        if not pending:
            break
        doc = pending[0]
        @firestore.transactional
        def claim(transaction):
            value = doc.reference.get(transaction=transaction).to_dict() or {}
            if value.get('status') != 'queued':
                return None
            transaction.update(doc.reference, {'status': 'processing', 'worker': nonce, 'updated_at': datetime.now(timezone.utc)})
            return value
        value = claim(db().transaction())
        if value is None:
            continue
        source = Path('/sources') / value['object']
        if not source.resolve().is_relative_to(Path('/sources')):
            raise ValueError('Invalid source path')
        try:
            result = put_file(value['owner'], value['memory'], source,
                progress=lambda total: heartbeat(total, doc.reference))
            @firestore.transactional
            def publish(transaction):
                current = doc.reference.get(transaction=transaction).to_dict() or {}
                if current.get('object') != value['object'] or current.get('worker') != nonce:
                    return
                transaction.update(doc.reference, {'status': 'attention' if result.get('coverage') == 'metadata' and result.get('issues') and value.get('attention_required', True) else 'complete',
                    'coverage': result.get('coverage', 'content'), 'issues': result.get('issues', {}),
                    'reader_version': result.get('reader_version', 2), 'chunks': result['chunks'], 'updated_at': datetime.now(timezone.utc)})
            publish(db().transaction())
            bucket().blob(value['object']).delete()
        except Exception as exc:
            # Preserve the staged source for an explicit retry, without losing other files.
            doc.reference.update({'status': 'failed', 'error': str(exc)[:400], 'updated_at': datetime.now(timezone.utc)})
    lease.set({'nonce': nonce, 'expires_at': datetime.now(timezone.utc)})
    if list(jobs().where(filter=firestore.FieldFilter('status', '==', 'queued')).limit(1).stream()):
        kick()


if __name__ == '__main__':
    drain()
