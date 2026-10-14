"""Seed a disposable RAM workspace and return changes for Android to commit."""
import base64
import json
from starlette.responses import JSONResponse
from ..services.mobile_scope import MobileScope, current, mobile_only


class MobileStateMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not mobile_only():
            return await self.app(scope, receive, send)
        state = MobileScope()
        token = current.set(state)
        started = False
        try:
            headers = dict(scope.get('headers', []))
            content_type = headers.get(b'content-type', b'').decode()
            body = bytearray()
            if scope['method'] in ('POST', 'PUT', 'PATCH') and 'application/json' in content_type:
                while True:
                    part = await receive()
                    if part['type'] == 'http.disconnect':
                        return
                    body.extend(part.get('body', b''))
                    if len(body) > 8 * 1024 * 1024:
                        return await JSONResponse({'detail': 'Request too large'}, 413)(scope, receive, send)
                    if not part.get('more_body'):
                        break
                value = json.loads(body) if body else {}
                seed = value.pop('_mobile_state', {}) if isinstance(value, dict) else {}
                state.seed(seed)
                if scope['path'] == '/context-events' and isinstance(value, dict) and value.get('event_id'):
                    state.operation_id = 'event:' + str(value['event_id'])
                body = json.dumps(value).encode()
                scope = {**scope, 'headers': [(k, v) for k, v in scope['headers'] if k.lower() != b'content-length'] +
                         [(b'content-length', str(len(body)).encode())]}
                delivered = False
                original_receive = receive

                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                    return await original_receive()
                receive = replay
            else:
                budget = headers.get(b'x-mobile-budget')
                if budget and len(budget) > 2048: raise ValueError('Budget too large')
                state.seed(json.loads(base64.b64decode(budget, validate=True)) if budget else {})
            metadata = headers.get(b'x-file-metadata')
            if metadata:
                if len(metadata) > 64000:
                    raise ValueError('File metadata is too large')
                file = json.loads(base64.b64decode(metadata, validate=True))
                from .routers.file_memories import owner, collection, key
                uid = owner(headers.get(b'x-file-memory-session', b'').decode())
                collection(uid).document(key(file['id'])).set(file)
            pending = None
            chunks = bytearray()

            async def output(message):
                nonlocal pending, started
                if message['type'] == 'http.response.start':
                    h = dict(message.get('headers', []))
                    if b'application/json' in h.get(b'content-type', b''):
                        pending = message
                        return
                if pending is not None and message['type'] == 'http.response.body':
                    chunks.extend(message.get('body', b''))
                    if message.get('more_body'):
                        return
                    data = json.loads(chunks) if chunks else {}
                    if isinstance(data, dict) and scope['path'] not in ('/', '/health', '/openapi.json'):
                        data['_mobile_changes'] = state.changes()
                    raw = json.dumps(data, default=str).encode()
                    start = {**pending, 'headers': [(k, v) for k, v in pending['headers'] if k.lower() != b'content-length'] +
                             [(b'content-length', str(len(raw)).encode())]}
                    await send(start)
                    started = True
                    await send({'type': 'http.response.body', 'body': raw})
                    pending = None
                    return
                if message['type'] == 'http.response.start': started = True
                await send(message)
            await self.app(scope, receive, output)
        except (ValueError, KeyError, TypeError):
            if started: raise
            await JSONResponse({'detail': 'Invalid mobile state'}, 422)(scope, receive, send)
        finally:
            current.reset(token)
            state.release()
