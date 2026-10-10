"""Index a prepared local Drive export using localhost inference and cloud vectors.

Run from backend: python -m scripts.local_bulk_index MANIFEST [--apply]
The default only validates local inputs; it makes no network requests.
"""
import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.services import drive_index


def local_url(value):
    parsed = urlparse(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'}):
        raise ValueError('Bulk inference must use an HTTP localhost endpoint')
    # drive_index.embed recognizes these two loopback names without cloud IAM.
    if parsed.hostname == '::1':
        raise ValueError('Use localhost or 127.0.0.1 for local inference')
    return value.rstrip('/')


def load_manifest(path):
    entries = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(entries, list) or not entries:
        raise ValueError('Manifest must be a nonempty JSON array')
    prepared, seen = [], set()
    for entry in entries:
        owner, memory = entry['owner'], entry['memory']
        # This is the hash of the phone file-memory capability, not the chat uid.
        if not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise ValueError('Use the existing file-memory owner hash')
        for field in ('account', 'id', 'name', 'url', 'mimeType', 'source_version'):
            if not isinstance(memory.get(field), str) or not memory[field]:
                raise ValueError('Missing file metadata: ' + field)
        source = (path.parent / entry['path']).resolve(strict=True)
        if not source.is_file():
            raise ValueError('Source must be a local file')
        identity = (owner, memory['account'], memory['id'])
        if identity in seen:
            raise ValueError('Duplicate file identity in manifest')
        seen.add(identity)
        prepared.append((owner, memory, source))
    return prepared


def check_model(url):
    response = httpx.get(url + '/health', timeout=15)
    response.raise_for_status()
    health = response.json()
    if (health.get('ready') is not True or health.get('model') != 'google/embeddinggemma-2'
            or health.get('revision') != drive_index.MODEL_REVISION or health.get('dimensions') != 768):
        raise ValueError('Local embedding model is not compatible with the cloud index')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--embedding-url', default='http://127.0.0.1:8080')
    parser.add_argument('--apply', action='store_true', help='Compute locally and upsert cloud vectors')
    args = parser.parse_args()
    url = local_url(args.embedding_url)
    entries = load_manifest(args.manifest.resolve(strict=True))
    print(json.dumps({'files': len(entries), 'mode': 'apply' if args.apply else 'validate',
                      'embedding_url': url}), flush=True)
    if not args.apply:
        return
    os.environ['EMBEDDING_URL'] = url
    if not drive_index.configured():
        raise ValueError('Set CHROMA_API_KEY, CHROMA_TENANT and CHROMA_DATABASE')
    check_model(url)
    for owner, memory, source in entries:
        result = drive_index.put_file(owner, memory, source)
        print(json.dumps({'file_id': memory['id'], **result}), flush=True)


if __name__ == '__main__':
    main()
