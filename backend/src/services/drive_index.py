"""Private per-capability Drive retrieval. Originals remain in Google Drive."""
import base64
import hashlib
import json
import io
import os
import subprocess
import tempfile
import time
import threading
from itertools import islice
from functools import lru_cache
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4

import httpx

MODEL_REVISION = '914f7f89142e33e77833254d9c9b90c3cef7303b'
COLLECTION = 'jarvis-drive-eg2-768-v1'
_token_cache = {}
_token_lock = threading.Lock()


def configured():
    return all(os.getenv(k) for k in ('CHROMA_API_KEY', 'CHROMA_TENANT', 'CHROMA_DATABASE', 'EMBEDDING_URL'))


@lru_cache(maxsize=1)
def index():
    import chromadb
    client = chromadb.CloudClient(api_key=os.environ['CHROMA_API_KEY'],
        tenant=os.environ['CHROMA_TENANT'], database=os.environ['CHROMA_DATABASE'],
        cloud_host=os.getenv('CHROMA_HOST', 'api.trychroma.com'))
    return client.get_or_create_collection(COLLECTION, embedding_function=None,
        metadata={'model': 'google/embeddinggemma-2', 'revision': MODEL_REVISION},
        configuration={'hnsw': {'space': 'cosine'}})


def embed(items, task='document'):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token
    url = os.environ['EMBEDDING_URL'].rstrip('/')
    if url.startswith(('http://localhost', 'http://127.0.0.1')):
        headers = {}
    else:
        with _token_lock:
            cached = _token_cache.get(url)
            if not cached or cached[1] < time.monotonic():
                cached = (fetch_id_token(Request(), url), time.monotonic() + 2700)
                _token_cache[url] = cached
            token = cached[0]
        headers = {'Authorization': 'Bearer ' + token}
    attempts = 1 if task == 'query' else 2
    for attempt in range(attempts):
        try:
            response = httpx.post(url + '/embed', headers=headers,
                json={'items': items, 'task': task}, timeout=25 if task == 'query' else 300)
        except httpx.TransportError:
            if attempt + 1 == attempts:
                raise
            time.sleep(1)
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
            time.sleep(1)
            continue
        break
    response.raise_for_status()
    result = response.json()
    if result.get('revision') != MODEL_REVISION or result.get('dimensions') != 768:
        raise ValueError('Embedding model version mismatch')
    vectors = result['embeddings']
    if len(vectors) != len(items) or any(len(v) != 768 for v in vectors):
        raise ValueError('Invalid embedding response')
    return vectors


@contextmanager
def source_stream(raw):
    if isinstance(raw, (str, Path)):
        with open(raw, 'rb') as stream:
            yield stream
    else:
        yield io.BytesIO(raw)


def source_digest(raw, progress=None):
    digest = hashlib.sha256()
    total = 0
    with source_stream(raw) as stream:
        while part := stream.read(1024 * 1024):
            digest.update(part)
            total += len(part)
            if progress and total % (64 * 1024 * 1024) == 0:
                progress(0)
    return digest.hexdigest()


def basic_chunks(raw, mime, title):
    """Yield bounded text/media units and source locators; never execute document instructions."""
    if mime == 'application/pdf':
        import pymupdf
        document = pymupdf.open(filename=str(raw), filetype='pdf') if isinstance(raw, (str, Path)) else pymupdf.open(stream=raw, filetype='pdf')
        with document as pdf:
            if pdf.is_encrypted:
                raise ValueError('Password-protected PDF is unsupported')
            for number, page in enumerate(pdf):
                text = page.get_text().strip()
                if len(text) >= 80:
                    for offset in range(0, len(text), 3000):
                        part = text[offset:offset + 3500]
                        yield {'kind': 'text', 'text': part}, part, f'page {number + 1}, text {offset}'
                else:
                    scale = min(1.0, 1600 / max(page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
                    yield {'kind': 'image', 'data': base64.b64encode(pix.tobytes('png')).decode()}, title, f'page {number + 1}'
    elif mime.startswith('text/'):
        with source_stream(raw) as source:
            reader = io.TextIOWrapper(source, encoding='utf-8-sig')
            offset, overlap = 0, ''
            while incoming := reader.read(3000 if overlap else 3500):
                part = overlap + incoming
                if part.strip():
                    yield {'kind': 'text', 'text': part}, part, f'characters {offset + 1}-{offset + len(part)}'
                offset += len(part) - 500
                overlap = part[-500:]
    elif mime.startswith('image/'):
        from PIL import Image
        with Image.open(str(raw) if isinstance(raw, (str, Path)) else io.BytesIO(raw)) as image:
            image.draft('RGB', (1600, 1600))
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=90)
            yield {'kind': 'image', 'data': base64.b64encode(output.getvalue()).decode()}, title, 'image'
    elif mime.startswith(('audio/', 'video/')):
        with tempfile.TemporaryDirectory() as folder:
            if isinstance(raw, (str, Path)):
                source = str(raw)
            else:
                source = os.path.join(folder, 'input')
                with open(source, 'wb') as stream:
                    stream.write(raw)
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', source], capture_output=True,
                text=True, check=True, timeout=10)
            duration = float(probe.stdout.strip())
            step = 30 if mime.startswith('audio/') else 10
            if duration <= 0:
                raise ValueError('Media has no readable duration')
            for start in range(0, int(duration) + 1, step):
                if start >= duration:
                    break
                audio = mime.startswith('audio/')
                target = os.path.join(folder, 'segment.wav' if audio else 'segment.mp4')
                command = ['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-i', source, '-t', str(step)]
                command += ['-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le'] if audio else [
                    '-an', '-vf', 'setpts=PTS-STARTPTS,fps=1:round=up:eof_action=pass,scale=384:384:force_original_aspect_ratio=decrease:force_divisible_by=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p']
                try:
                    subprocess.run(command + [target], capture_output=True, check=True, timeout=60)
                except subprocess.CalledProcessError as exc:
                    raise ValueError('Audio or video source could not be decoded') from exc
                with open(target, 'rb') as stream:
                    segment = stream.read(8_000_001)
                if len(segment) > 8_000_000:
                    raise ValueError('Media segment exceeds embedding input limit')
                yield {'kind': 'audio' if audio else 'video', 'data': base64.b64encode(segment).decode()}, title, f'seconds {start}-{min(start + step, duration):g}'
    else:
        raise ValueError('Indexing supports PDF, UTF-8 text, images, audio and video')


def chunks(raw, mime, title, coverage=None):
    from .file_readers import read, Coverage
    yield from read(raw, mime, title, coverage or Coverage(), basic_chunks)


def where_file(owner, account, file_id):
    return {'$and': [{'owner': owner}, {'account': account}, {'file_id': file_id}]}


def put_file(owner, memory, raw, progress=None):
    if raw is None:
        raise ValueError('File is empty')
    from .file_readers import Coverage, READER_VERSION
    coverage = Coverage()
    digest = source_digest(raw, progress)
    coll = index()
    scope = where_file(owner, memory['account'], memory['id'])
    previous = coll.get(where=scope, include=['metadatas'], limit=1)
    partial = coll.get(where={'$and': [*scope['$and'], {'complete': False}]}, include=['metadatas'], limit=1)
    if previous['ids'] and not partial['ids'] and all(m.get('digest') == digest and m.get('complete') is True and m.get('reader_version') == READER_VERSION for m in previous['metadatas']):
        offset = 0
        while True:
            records = coll.get(where=scope, include=['metadatas'], limit=100, offset=offset)
            if not records['ids']:
                break
            coll.update(ids=records['ids'], metadatas=[{**m, 'source_version': memory.get('source_version', ''),
                'name': memory['name'], 'url': memory['url']} for m in records['metadatas']])
            offset += len(records['ids'])
            if progress:
                progress(offset)
        return {'status': 'unchanged', 'chunks': previous['metadatas'][0].get('chunk_total', 1),
            'coverage': previous['metadatas'][0].get('coverage', 'content'),
            'issues': json.loads(previous['metadatas'][0].get('reader_issues', '{}')), 'reader_version': READER_VERSION}
    identity = hashlib.sha256(f"{owner}:{memory['account']}:{memory['id']}".encode()).hexdigest()
    iterator = iter(chunks(raw, memory['mimeType'], memory['name'], coverage))
    generation = uuid4().hex
    total = 0
    base = {'owner': owner, 'account': memory['account'], 'file_id': memory['id'],
        'name': memory['name'], 'url': memory['url'], 'digest': digest,
        'source_version': memory.get('source_version', ''),
        'mimeType': memory['mimeType'], 'generation': generation, 'reader_version': READER_VERSION}
    try:
        while batch := list(islice(iterator, 2)):
            vectors = embed([{k: v for k, v in u[0].items() if not k.startswith('_')} for u in batch])
            batch_ids = [hashlib.sha256(f'{identity}:{generation}:{total + n}'.encode()).hexdigest()
                for n in range(len(batch))]
            batch_metadata = [{**base, 'locator': unit[2], 'complete': False,
                'unit_kind': unit[0]['kind'],
                'content_kind': unit[0].get('_content_kind', 'content' if unit[0]['kind'] == 'text' else 'media_reference')} for unit in batch]
            coll.upsert(ids=batch_ids, embeddings=vectors, documents=[u[1] for u in batch], metadatas=batch_metadata)
            total += len(batch)
            if progress:
                progress(total)
        if not total:
            raise ValueError('No readable content')
        generation_scope = {'$and': [*scope['$and'], {'generation': generation}]}
        offset = 0
        while True:
            records = coll.get(where=generation_scope, limit=100, offset=offset, include=['metadatas'])
            if not records['ids']:
                break
            coll.update(ids=records['ids'], metadatas=[{**m, 'complete': True, 'chunk_total': total,
                'coverage': coverage.level, 'reader_issues': json.dumps(dict(coverage.issues))} for m in records['metadatas']])
            offset += len(records['ids'])
    except Exception:
        coll.delete(where={'$and': [*scope['$and'], {'generation': generation}]})
        raise
    coll.delete(where={'$and': [*scope['$and'], {'generation': {'$ne': generation}}]})
    return {'status': 'indexed', 'chunks': total, **coverage.report()}


def evidence(owner, account, file_id, version, query):
    scope = {'$and': [*where_file(owner, account, file_id)['$and'], {'complete': True}, {'source_version': version}]}
    result = index().query(query_embeddings=embed([{'kind': 'text', 'text': query}], 'query'),
        where=scope, n_results=8, include=['metadatas', 'documents'])
    return format_passages(result)


def format_passages(result):
    passages = []
    for text, metadata in zip(result['documents'][0], result['metadatas'][0]):
        media = metadata.get('unit_kind') in {'image', 'audio', 'video'} or (
            text == metadata.get('name') and metadata.get('mimeType', '').startswith(('image/', 'audio/', 'video/', 'application/pdf')))
        passages.append({'text': 'Media locator in the original source; no transcript or visual description is provided by this passage.' if media else text,
            'file_id': metadata.get('file_id', ''), 'name': metadata.get('name', ''), 'url': metadata.get('url', ''),
            'locator': metadata['locator'], 'coverage': metadata.get('coverage', 'content'),
            'content_kind': 'media_reference' if media else metadata.get('content_kind', 'content')})
    return {'status': 'ok' if passages else 'pending', 'evidence': passages}


def search_contents(owner, account, query, files):
    if not files:
        return {'status': 'pending', 'evidence': []}
    claims = [{'$and': [{'file_id': f['file_id']}, {'source_version': f['source_version']}]} for f in files]
    claimed = claims[0] if len(claims) == 1 else {'$or': claims}
    scope = {'$and': [{'owner': owner}, {'account': account}, {'complete': True}, claimed]}
    result = index().query(query_embeddings=embed([{'kind': 'text', 'text': query}], 'query'),
        where=scope, n_results=12, include=['metadatas', 'documents'])
    return format_passages(result)


def search(owner, account, query):
    coll = index()
    result = coll.query(query_embeddings=embed([{'kind': 'text', 'text': query}], 'query'),
        where={'$and': [{'owner': owner}, {'account': account}, {'complete': True}]}, n_results=12,
        include=['metadatas', 'distances'])
    # Return locators, not source text: the phone must recheck current Drive access first.
    return {'matches': [dict(m, distance=d) for m, d in
        zip(result['metadatas'][0], result['distances'][0])]}
