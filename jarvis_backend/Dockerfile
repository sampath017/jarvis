# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast python dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install the MCP Google Tools server globally
RUN npm install -g google-tools-mcp

# Set the working directory in the container
WORKDIR /app

# Enable bytecode compilation and offline sync
ENV UV_COMPILE_BYTECODE=1
ENV UV_PYTHON_DOWNLOADS=never

# Copy the dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install Python dependencies (frozen to lockfile)
RUN uv sync --frozen --no-cache --no-install-project

# Copy the rest of the application code
COPY src ./src
COPY README.md ./

# Create an empty checkpoints.sqlite to avoid startup errors
RUN touch checkpoints.sqlite

# Ensure the project is installed and environment is ready
RUN uv sync --frozen --no-cache

# Use the virtual environment's python directly for faster startup
ENV PATH="/app/.venv/bin:$PATH"

# Cloud Run uses the PORT environment variable
EXPOSE 8080

# Run the application
CMD ["python", "-m", "src.main"]
