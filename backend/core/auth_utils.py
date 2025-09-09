from typing import Any, Dict, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from . import jwt as jwt_core

try:
    from ..services import user_service, auth_service  # services live at backend/services
except Exception:  # pragma: no cover - import fallback for script execution contexts
    user_service = None  # type: ignore
    auth_service = None  # type: ignore

# reuse same oauth2 scheme as auth_service when available, otherwise create one
if auth_service and getattr(auth_service, "oauth2_scheme", None):
    oauth2_scheme = auth_service.oauth2_scheme  # type: ignore
else:
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def create_tokens_for_subject(subject: str) -> Dict[str, Any]:
    """
    Create access + refresh tokens for a subject (user id or email).
    Returns a dict compatible with TokenResponse fields (access_token, refresh_token, token_type, expires_in).
    """
    access = jwt_core.create_access_token(subject=subject)
    refresh = jwt_core.create_refresh_token(subject=subject)
    # expires_in in seconds (attempt to read setting, fallback to 3600)
    try:
        expires_in = int(getattr(jwt_core, "settings").ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    except Exception:
        expires_in = 60 * 60
    return {
        "access_token": access,
        "token_type": "bearer",
        "refresh_token": refresh,
        "expires_in": expires_in,
    }


async def get_user_from_token(token: str) -> Optional[Any]:
    """
    Decode token and load the user. Returns user object or None.
    """
    try:
        payload = jwt_core.decode_token(token)
    except Exception:
        return None

    subject = payload.get("sub")
    if not subject:
        return None

    # try by id first
    user = None
    try:
        if user_service:
            try:
                user = await user_service.get_user_by_id(int(subject))
            except Exception:
                user = await user_service.get_user_by_email(subject)
    except Exception:
        user = None

    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Any:
    """
    FastAPI dependency: returns current user or raises 401.
    Prefer using auth_service.get_current_user where available; this mirrors that behavior.
    """
    # prefer auth_service.get_current_user if present to keep single source of truth
    if auth_service and getattr(auth_service, "get_current_user", None):
        return await auth_service.get_current_user(token)  # type: ignore

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = await get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token or user not found")
    return user


def is_admin(user: Any) -> bool:
    return bool(getattr(user, "is_admin", False))


async def require_admin(current_user: Any = Depends(get_current_user)) -> Any:
    """
    Dependency to ensure current user is an admin.
    """
    if not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


async def require_owner_or_admin(target_user_id: int, current_user: Any = Depends(get_current_user)) -> Any:
    """
    Dependency to require that current_user is the owner (target_user_id) or an admin.
    """
    current_id = getattr(current_user, "id", None)
    if current_id != target_user_id and not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return current_user
