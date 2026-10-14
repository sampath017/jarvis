"""Build-time CPU checks for every encoder; uses only synthetic media."""
import os
import tempfile
import subprocess
import time
import wave
import numpy as np
import torch
from PIL import Image
from sentence_transformers import SentenceTransformer

torch.set_num_threads(2)
model = SentenceTransformer('google/embeddinggemma-2', revision=os.environ['MODEL_REVISION'],
    device='cpu', model_kwargs={'torch_dtype': torch.float32})
with tempfile.TemporaryDirectory() as folder:
    audio = os.path.join(folder, 'test.wav')
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(bytes(32000))
    video = os.path.join(folder, 'test.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=128x128:r=1',
        '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', video], check=True)
    for kind, item in [('text', 'task: search result | query: build check'),
        ('image', {'image': Image.new('RGB', (128, 128), 'blue')}),
        ('audio', {'audio': audio}), ('video', {'video': video})]:
        started = time.monotonic()
        vector = model.encode(item, normalize_embeddings=True)
        assert vector.shape == (768,) and np.isfinite(vector).all(), kind
        print(f'CPU {kind} smoke passed in {time.monotonic() - started:.2f}s', flush=True)
