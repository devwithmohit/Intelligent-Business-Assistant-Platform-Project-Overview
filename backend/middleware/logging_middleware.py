import time
import uuid
import logging
from typing import Callable

from structlog.contextvars import bind_contextvars, clear_contextvars
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("backend.request")


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware to log incoming requests and responses with a request-id and timing.
    Register in FastAPI app with: app.add_middleware(LoggingMiddleware)
    """

    def __init__(self, app, *, log_level: int = logging.INFO) -> None:
        super().__init__(app)
        self.log_level = log_level

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        clear_contextvars()
        request_id = str(uuid.uuid4())
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        client = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
            client=client,
        )

        start = time.perf_counter()
        logger.log(
            self.log_level,
            "request.start",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "query": query,
                "client": client,
                "user_agent": user_agent,
            },
        )

        try:
            response = await call_next(request)
            elapsed = time.perf_counter() - start
            status_code = getattr(response, "status_code", None)

            # attach request id for downstream tracing / clients
            if isinstance(response, Response):
                response.headers.setdefault("X-Request-ID", request_id)

            logger.log(
                self.log_level,
                "request.complete",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "query": query,
                    "status_code": status_code,
                    "client": client,
                    "elapsed_s": round(elapsed, 4),
                },
            )
            return response
        except Exception:
            elapsed = time.perf_counter() - start
            logger.exception(
                "request.error",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client": client,
                    "elapsed_s": elapsed,
                },
            )
            raise
        finally:
            clear_contextvars()
