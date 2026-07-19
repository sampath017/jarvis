# Use official slim Python image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy configuration and dependency specs
COPY pyproject.toml .env.example /app/

# Install application dependencies directly to system environment
RUN uv pip install --system -r pyproject.toml

# Copy source tree
COPY src /app/src

# Expose server port
EXPOSE 8080

# Run uvicorn server on port 8080
CMD uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}
