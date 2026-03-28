from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_WORKFLOW_DIR = _BACKEND_DIR.parent / "data" / "workflows"
_DEFAULT_WORKFLOW_STATE_DIR = _BACKEND_DIR.parent / "data" / "workflow_states"
_DEFAULT_CHROMA_DIR = _BACKEND_DIR.parent / "data" / "vector_db" / "chroma"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and backend/.env."""

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Intelligent Business Assistant"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str | None = None

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    REDIS_URL: str | None = None
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60

    OPENROUTER_KEY: str | None = None
    OPENROUTER_URL: str = "https://api.openrouter.ai"
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_URL: str = "https://api.deepseek.ai"

    WORKFLOW_DIR: str = str(_DEFAULT_WORKFLOW_DIR)
    WORKFLOW_STATE_DIR: str = str(_DEFAULT_WORKFLOW_STATE_DIR)
    ALLOWED_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])

    CHROMA_DIR: str = str(_DEFAULT_CHROMA_DIR)
    CHROMA_API_KEY: str | None = None
    EMBEDDING_MODEL: str = "deeps-embed-1"

    MODEL_PREFERENCES: list[str] = Field(
        default_factory=lambda: ["openrouter", "deepseek"]
    )
    LLM_DEFAULT_PROVIDER: str = "openrouter"

    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    TEST_EMAIL: str | None = None
    TEST_PASSWORD: str | None = None

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _parse_allowed_origins(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return ["*"]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ["*"]
            if stripped.startswith("[") and stripped.endswith("]"):
                parsed = [
                    item.strip().strip('"').strip("'")
                    for item in stripped[1:-1].split(",")
                ]
                cleaned = [item for item in parsed if item]
                return cleaned or ["*"]
            return [item.strip() for item in stripped.split(",") if item.strip()]
        raise TypeError("ALLOWED_ORIGINS must be a list or comma-separated string")

    @field_validator("MODEL_PREFERENCES", mode="before")
    @classmethod
    def _parse_model_preferences(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return ["openrouter", "deepseek"]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError("MODEL_PREFERENCES must be a list or comma-separated string")


settings = Settings()
