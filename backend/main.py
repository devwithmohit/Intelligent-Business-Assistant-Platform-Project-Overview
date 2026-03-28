import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import agents as agents_router
from .api.v1 import analytics as analytics_router
from .api.v1 import auth as auth_router
from .api.v1 import chat as chat_router
from .api.v1 import integrations as integrations_router
from .api.v1 import tasks as tasks_router
from .api.v1 import users as users_router
from .api.v1 import workflows as workflows_router
from .core.config import settings
from .core.logging_config import configure_logging
from .middleware.logging_middleware import LoggingMiddleware
from .middleware.rate_limit import init_rate_limiter

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(title=getattr(settings, "APP_NAME", "IBA Backend"), version="0.1.0")

# CORS
allow_origins = getattr(settings, "ALLOWED_ORIGINS", ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware (structured request logging)
app.add_middleware(LoggingMiddleware)

def _include_router(module) -> None:
    router = getattr(module, "router", None)
    if router is None:
        logger.warning(
            "router module has no router; skipping registration",
            extra={"module": getattr(module, "__name__", repr(module))},
        )
        return
    app.include_router(router)


def _build_default_rate_limit(requests: int, window_seconds: int) -> str:
    if window_seconds <= 1:
        return f"{requests}/second"
    if window_seconds == 60:
        return f"{requests}/minute"
    if window_seconds == 3600:
        return f"{requests}/hour"
    return f"{requests}/{window_seconds} seconds"


for router_module in (
    auth_router,
    users_router,
    agents_router,
    analytics_router,
    chat_router,
    integrations_router,
    tasks_router,
    workflows_router,
):
    _include_router(router_module)


@app.on_event("startup")
async def on_startup():
    # init rate limiter (slowapi) if available
    try:
        redis_url = getattr(settings, "REDIS_URL", None)
        default_limit = _build_default_rate_limit(
            getattr(settings, "RATE_LIMIT_REQUESTS", 100),
            getattr(settings, "RATE_LIMIT_WINDOW", 60),
        )
        init_rate_limiter(app, redis_url=redis_url, default_limits=[default_limit])
    except Exception:
        logger.exception("Failed to initialize rate limiter")

    # create sqlite tables in dev if needed (non-destructive)
    try:
        from .core import database

        database.init_db(create_tables=True)
    except Exception:
        logger.exception("Database initialization failed")


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}


# Expose app for test clients (e.g. TestClient(import "backend.main:app"))
