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

    EXEMPT_PATHS = {
        "/",
        "/health",
        "/notifications",
        "/sync/pull",
        "/sync/push",
    }

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

        # 2. Exempt lightweight background polling, health probes, and sync endpoints
        path = request.url.path
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        # 3. Enforce rate limit by real client identity (X-User-ID or X-Forwarded-For IP)
        # Note: Behind Cloud Run / Load Balancers, request.client.host is the internal proxy IP (169.254.169.126)
        user_id = request.headers.get("x-user-id")
        forwarded = request.headers.get("x-forwarded-for")
        if user_id:
            client_key = f"user:{user_id}"
        elif forwarded:
            client_key = f"ip:{forwarded.split(',')[0].strip()}"
        elif request.client:
            client_key = f"ip:{request.client.host}"
        else:
            client_key = "unknown"

        if not self._check_rate_limit(client_key):
            logger.warning(
                "Rate limit exceeded in RequestLimitingMiddleware for key: %s (path: %s)",
                client_key,
                path,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Try again later."},
            )

        return await call_next(request)

    def _check_rate_limit(self, key: str) -> bool:
        """Rate limit check (sliding window)."""
        now = time.time()
        window = 60.0
        limit = max(RATE_LIMIT_PER_USER_PER_MINUTE * 2, 60)

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
