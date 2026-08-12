"""
API Middlewares — request size limits, rate limiting, and structured logging.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing_extensions import override
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from ..settings import MAX_REQUEST_SIZE_BYTES, RATE_LIMIT_PER_USER_PER_MINUTE

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter: key -> list of request timestamps
_rate_limit_tracker: dict[str, list[float]] = defaultdict(list)


class RequestLimitingMiddleware(BaseHTTPMiddleware):
    """Enforces request payload size limits and rate limiting."""

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 1. Enforce payload size limit
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > MAX_REQUEST_SIZE_BYTES:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Request payload too large"},
                    )
            except ValueError:
                pass

        # 2. Enforce simple in-memory rate limit by client IP
        # Note: Production deployments behind load balancers should read X-Forwarded-For
        client_ip = request.client.host if request.client else "unknown"
        if not self._check_rate_limit(client_ip):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Try again later."},
            )

        return await call_next(request)

    def _check_rate_limit(self, key: str) -> bool:
        """Rate limit check (sliding window)."""
        now = time.time()
        window = 60.0
        limit = RATE_LIMIT_PER_USER_PER_MINUTE

        # Prune stale timestamps
        timestamps = _rate_limit_tracker[key]
        _rate_limit_tracker[key] = [t for t in timestamps if now - t < window]

        # Check limit
        if len(_rate_limit_tracker[key]) >= limit:
            return False

        _rate_limit_tracker[key].append(now)
        return True


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Structured logging middleware injecting correlation IDs."""

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get(
            "x-correlation-id") or str(uuid.uuid4())
        start_time = time.perf_counter()

        # Place correlation ID on state for downstream access
        request.state.correlation_id = correlation_id

        logger.info(
            "API Request Start",
            extra={
                "method": request.method,
                "url": str(request.url.path),
                "correlation_id": correlation_id,
            },
        )

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000
            response.headers["x-correlation-id"] = correlation_id

            logger.info(
                "API Request End",
                extra={
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "correlation_id": correlation_id,
                },
            )
            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "API Request Error",
                extra={
                    "error": str(e),
                    "duration_ms": round(duration_ms, 2),
                    "correlation_id": correlation_id,
                },
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": f"Internal server error: {e}"},
            )
