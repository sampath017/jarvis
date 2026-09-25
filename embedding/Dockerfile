FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 HF_HOME=/opt/model-cache TOKENIZERS_PARALLELISM=false PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.1 torchcodec==0.17.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
ARG MODEL_REVISION=914f7f89142e33e77833254d9c9b90c3cef7303b
ENV MODEL_REVISION=$MODEL_REVISION
RUN python -c "import os; from huggingface_hub import snapshot_download; snapshot_download('google/embeddinggemma-2', revision=os.environ['MODEL_REVISION'])"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 EMBEDDING_PARALLELISM=2 TORCH_THREADS=2
COPY smoke.py .
RUN python smoke.py
COPY app.py .
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
