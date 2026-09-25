FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ="Asia/Kolkata" \
    PORT=8080

WORKDIR /app

# Install build dependencies and timezone data for IST
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && echo "Asia/Kolkata" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Pin the build tool and avoid an additional container-registry dependency.
RUN pip install --no-cache-dir uv==0.11.20

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Install dependencies directly into system Python
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy source code and default env file
COPY src/ ./src/
COPY .env ./

# Ensure data directory exists for local SQLite storage
RUN mkdir -p /app/data /app/logs

EXPOSE 8080

# Start Uvicorn bound to 0.0.0.0 and dynamic $PORT for Cloud Run
CMD ["sh", "-c", "python -m uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
