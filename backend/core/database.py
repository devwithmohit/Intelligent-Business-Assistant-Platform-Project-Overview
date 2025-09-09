import os
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# try to load project settings, fallback to env / sqlite for local dev
try:
    from .config import settings  # type: ignore

    DATABASE_URL: Optional[str] = getattr(settings, "DATABASE_URL", None)
except Exception:
    DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    sqlite_path = os.path.join(here, "data", "dev.db")
    DATABASE_URL = f"sqlite:///{sqlite_path}"

# create engine with sensible defaults
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # sqlite needs check_same_thread for sync use in web apps
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

# Session factory for sync DB access
SessionLocal: sessionmaker = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)

# Base declarative class for ORM models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a DB session and ensures it's closed afterwards.
    Usage:
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(create_tables: bool = False) -> None:
    if create_tables:
        Base.metadata.create_all(bind=engine)
