import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# load .env for local dev if python-dotenv available
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

# config/settings
try:
    from .core import config as core_config  # type: ignore
    settings = core_config.settings
except Exception:
    # minimal fallback settings for local dev
    class _S:  # pragma: no cover - fallback
        APP_NAME = "Intelligent Business Assistant"
        ALLOWED_ORIGINS: List[str] = ["*"]
        REDIS_URL = None
        RATE_LIMIT_REQUESTS = 100
        RATE_LIMIT_WINDOW = 60

    settings = _S()

# middlewares / utilities
from .middleware.logging_middleware import LoggingMiddleware  # request/response logger
from .middleware.rate_limit import init_rate_limiter  # rate limiter init

# routers
from .api.v1 import auth as auth_router  # auth.router
from .api.v1 import users as users_router
from .api.v1 import agents as agents_router
from .api.v1 import analytics as analytics_router
from .api.v1 import chat as chat_router
from .api.v1 import integrations as integrations_router
from .api.v1 import tasks as tasks_router

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

# include API routers
app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(agents_router.router)
app.include_router(analytics_router.router)
app.include_router(chat_router.router)
app.include_router(integrations_router.router)
app.include_router(tasks_router.router)


@app.on_event("startup")
async def on_startup():
    # init rate limiter (slowapi) if available
    try:
        redis_url = getattr(settings, "REDIS_URL", None)
        default_limit = f"{getattr(settings, 'RATE_LIMIT_REQUESTS', 100)}/minute"
        init_rate_limiter(app, redis_url=redis_url, default_limits=[default_limit])
    except Exception:
        # don't block startup — rate limiter optional
        pass

    # create sqlite tables in dev if needed (non-destructive)
    try:
        from .core import database

        database.init_db(create_tables=True)
    except Exception:
        pass


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}


# Expose app for test clients (e.g. TestClient(import "backend.main:app"))
