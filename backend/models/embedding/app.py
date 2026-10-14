"""Private IAM-protected Cloud Run embedding service. No source logging/storage."""
import base64
import io
import os
import tempfile
import threading
import time
import subprocess
import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL = 'google/embeddinggemma-2'
REVISION = os.environ.get('MODEL_REVISION', '914f7f89142e33e77833254d9c9b90c3cef7303b')
model = None
model_load_seconds = None
slots = threading.BoundedSemaphore(int(os.getenv('EMBEDDING_PARALLELISM', '2')))


@asynccontextmanager
async def lifespan(app):
    global model, model_load_seconds
    started = time.monotonic()
    import torch
    # Cloud Run startup CPU boost supplies more cores while weights are loaded.
    torch.set_num_threads(int(os.getenv('TORCH_INIT_THREADS', '8')))
    torch.set_num_interop_threads(1)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, revision=REVISION,
        device='cpu', model_kwargs={'torch_dtype': torch.float32})
    torch.set_num_threads(int(os.getenv('TORCH_THREADS', '2')))
    model_load_seconds = round(time.monotonic() - started, 2)
    yield


app = FastAPI(lifespan=lifespan)


class Item(BaseModel):
    kind: Literal['text', 'image', 'audio', 'video'] = 'text'
    text: str = Field(default='', max_length=20000)
    data: str = Field(default='', max_length=12_000_000)


class Batch(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=16)
    task: Literal['query', 'document'] = 'document'


@app.get('/health')
def health():
    return {'ready': model is not None, 'model': MODEL, 'revision': REVISION, 'dimensions': 768,
        'device': 'cpu', 'parallelism': int(os.getenv('EMBEDDING_PARALLELISM', '2')),
        'model_load_seconds': model_load_seconds}


@app.post('/embed')
def embed(batch: Batch):
    if model is None:
        raise HTTPException(503, 'Embedding model is loading')
    if sum(len(i.data) + len(i.text) for i in batch.items) > 16_000_000:
        raise HTTPException(413, 'Embedding batch too large')
    if not slots.acquire(timeout=1):
        raise HTTPException(429, 'Embedding worker busy; retry shortly', headers={'Retry-After': '2'})
    started = time.monotonic()
    try:
        return encode_batch(batch, started)
    finally:
        slots.release()


def encode_batch(batch, started):
    vectors = []
    with tempfile.TemporaryDirectory() as folder:
        for n, item in enumerate(batch.items):
            if item.kind == 'text':
                if not item.text.strip():
                    raise HTTPException(422, 'Empty text')
                value = ('task: search result | query: ' if batch.task == 'query' else 'title: none | text: ') + item.text
            else:
                try:
                    raw = base64.b64decode(item.data, validate=True)
                    if not raw:
                        raise ValueError('empty')
                    if item.kind == 'image':
                        from PIL import Image
                        image = Image.open(io.BytesIO(raw))
                        if image.width * image.height > 40_000_000:
                            raise ValueError('image too large')
                        image.thumbnail((1600, 1600))
                        value = {'image': image.convert('RGB')}
                    else:
                        path = os.path.join(folder, f'{n}.{"wav" if item.kind == "audio" else "mp4"}')
                        with open(path, 'wb') as stream:
                            stream.write(raw)
                        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'json', path], capture_output=True, text=True, timeout=10, check=True)
                        duration = float(json.loads(probe.stdout)['format']['duration'])
                        limit = 30 if item.kind == 'audio' else 10
                        # PCM sample boundaries can round an exact 30-second cut
                        # a fraction of a millisecond upward. Allow codec rounding.
                        if duration > limit + 0.01 or duration <= 0:
                            raise ValueError(f'{item.kind} clip must be at most {limit} seconds')
                        value = {item.kind: path}
                except Exception as exc:
                    raise HTTPException(422, 'Invalid media input') from exc
            # Each request uses a bounded media unit; two requests can execute concurrently.
            vector = model.encode(value, normalize_embeddings=True).tolist()
            if len(vector) != 768:
                raise HTTPException(500, 'Unexpected embedding dimensions')
            vectors.append(vector)
    return {'model': MODEL, 'revision': REVISION, 'dimensions': 768, 'embeddings': vectors,
        'processing_ms': round((time.monotonic() - started) * 1000, 1)}
