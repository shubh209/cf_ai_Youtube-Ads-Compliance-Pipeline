import os
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in memory rate limiter for pilot deployments."""

    def __init__(self, app, max_requests: int | None = None, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests or int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
        self.window_seconds = window_seconds
        # ponytail: separate bucket per route type; hourly window for uploads
        self.upload_max = int(os.getenv("UPLOAD_RATE_LIMIT_PER_HOUR", "10"))
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)

        now = time.time()
        key = self._client_key(request)

        if request.url.path == "/audit/upload":
            # Hourly window for uploads
            bucket = self._hits[f"upload:{key}"]
            while bucket and now - bucket[0] > 3600:
                bucket.popleft()
            if len(bucket) >= self.upload_max:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Upload rate limit exceeded. Try again later."},
                )
            bucket.append(now)
            return await call_next(request)

        if request.url.path == "/audit":
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                )
            bucket.append(now)

        return await call_next(request)
