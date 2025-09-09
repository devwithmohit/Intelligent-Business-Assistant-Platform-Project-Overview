"""
Rate limiter integration using slowapi (limits + redis/memory backend).

Usage:
- Call init_rate_limiter(app, redis_url="redis://localhost:6379/0", default_limits=["100/minute"])
  during app startup (e.g. in backend/main.py).
- Use @rate_limit("10/minute") decorator on endpoints or use limiter.limit(...) directly.

Requires: pip install slowapi redis
"""
from typing import Iterable, Optional

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

# global limiter instance (initialized in init_rate_limiter)
limiter: Limiter = Limiter(key_func=get_remote_address)


def init_rate_limiter(app: FastAPI, redis_url: Optional[str] = None, default_limits: Optional[Iterable[str]] = None):
    """
    Initialize the rate limiter and register middleware + exception handler.

    - app: FastAPI instance
    - redis_url: optional storage URI like "redis://localhost:6379/0". If None, slowapi uses memory storage.
    - default_limits: iterable of limit strings, e.g. ["100/minute", "1000/day"]
    """
    global limiter

    storage_uri = redis_url if redis_url else "memory://"
    limiter = Limiter(key_func=get_remote_address, storage_uri=storage_uri, default_limits=list(default_limits or []))

    # attach to app state so other modules can import limiter from here and access app.state if needed
    app.state.limiter = limiter

    # register middleware and exception handler
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def rate_limit(limit_str: str):
    """
    Simple decorator to apply a rate limit to a route.
    Example:
      @router.get("/ping")
      @rate_limit("10/minute")
      async def ping():
          return {"ok": True}
    """
    def decorator(fn):
        return limiter.limit(limit_str)(fn)
    return decorator