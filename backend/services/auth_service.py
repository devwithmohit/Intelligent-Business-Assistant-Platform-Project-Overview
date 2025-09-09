import typing as t
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from jose import jwt, JWTError

from ...services import user_service
from ...schemas import auth_schemas, user_schemas
from ...core import config

try:
    SETTINGS = config.settings  # typical pattern: core.config.settings
except Exception:
    # minimal fallback values (replace with real secret in .env)
    class _S:
        SECRET_KEY = "change-me"
        ALGORITHM = "HS256"
        ACCESS_TOKEN_EXPIRE_MINUTES = 60
        REFRESH_TOKEN_EXPIRE_DAYS = 7

    SETTINGS = _S()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class AuthError(Exception):
    pass


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def _create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=SETTINGS.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {"sub": str(subject), "exp": int(expire.timestamp()), "iat": int(datetime.utcnow().timestamp())}
    return jwt.encode(to_encode, SETTINGS.SECRET_KEY, algorithm=SETTINGS.ALGORITHM)


def _create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(days=getattr(SETTINGS, "REFRESH_TOKEN_EXPIRE_DAYS", 7)))
    to_encode = {"sub": str(subject), "exp": int(expire.timestamp()), "iat": int(datetime.utcnow().timestamp()), "typ": "refresh"}
    return jwt.encode(to_encode, SETTINGS.SECRET_KEY, algorithm=SETTINGS.ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SETTINGS.SECRET_KEY, algorithms=[SETTINGS.ALGORITHM])
        return payload
    except JWTError as e:
        raise AuthError("Invalid token") from e


async def _create_token_response_for_user(user: t.Any) -> dict:
    """
    Returns dict compatible with TokenResponse schema.
    `user` can be ORM model or dict; Pydantic TokenResponse.user uses UserRead with orm_mode.
    """
    subject = getattr(user, "id", None) or getattr(user, "email", None)
    if subject is None:
        raise AuthError("Cannot create token for user without id/email")

    access_token = _create_access_token(subject=str(subject))
    refresh_token = _create_refresh_token(subject=str(subject))

    # compute expiry seconds
    expires_in = int(SETTINGS.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "user": user,
    }


async def login(email: str, password: str) -> auth_schemas.TokenResponse:
    user = await user_service.get_user_by_email(email)
    if not user:
        raise AuthError("Invalid credentials")

    hashed = getattr(user, "password", None)
    if not hashed or not verify_password(password, hashed):
        raise AuthError("Invalid credentials")

    if getattr(user, "is_active", True) is False:
        raise AuthError("User is inactive")

    token_obj = await _create_token_response_for_user(user)
    return auth_schemas.TokenResponse(**token_obj)


async def register(payload: auth_schemas.RegisterRequest) -> auth_schemas.TokenResponse:
    # Ensure email not already used
    existing = await user_service.get_user_by_email(payload.email)
    if existing:
        raise AuthError("Email already registered")

    user_in = user_schemas.UserCreate(
        name=payload.name,
        email=payload.email,
        password=get_password_hash(payload.password),
    )
    created = await user_service.create_user(user_in)
    token_obj = await _create_token_response_for_user(created)
    return auth_schemas.TokenResponse(**token_obj)


async def refresh_token(refresh_token: str) -> auth_schemas.TokenResponse:
    try:
        payload = _decode_token(refresh_token)
    except AuthError:
        raise AuthError("Invalid refresh token")

    # ensure token is actually a refresh token if typ present
    if payload.get("typ") and payload.get("typ") != "refresh":
        raise AuthError("Invalid token type")

    subject = payload.get("sub")
    if not subject:
        raise AuthError("Invalid token payload")

    # try to load user (by id or email)
    user = None
    try:
        user = await user_service.get_user_by_id(int(subject))
    except Exception:
        # try by email
        user = await user_service.get_user_by_email(subject)

    if not user:
        raise AuthError("User not found for token")

    token_obj = await _create_token_response_for_user(user)
    return auth_schemas.TokenResponse(**token_obj)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> t.Any:
    """
    Dependency to return current user from access token.
    Raises HTTPException 401 when token invalid or user not found.
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = _decode_token(token)
    except AuthError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    # attempt to fetch by id first
    user = None
    try:
        user = await user_service.get_user_by_id(int(subject))
    except Exception:
        user = await user_service.get_user_by_email(subject)

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user