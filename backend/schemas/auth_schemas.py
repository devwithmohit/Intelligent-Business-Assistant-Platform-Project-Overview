from typing import Optional
from pydantic import BaseModel, EmailStr, Field

try:
    # import user read schema for optional inclusion in token responses
    from .user_schemas import UserRead  # type: ignore
except Exception:
    UserRead = None  # fallback for import ordering


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    name: Optional[str] = Field(None, example="Jane Doe")
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    # include user info if service provides it; allow None if not present
    user: Optional[UserRead] = None

    class Config:
        orm_mode = True
