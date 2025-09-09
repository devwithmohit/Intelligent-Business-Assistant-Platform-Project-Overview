from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from jose import jwt, JWTError

try:
    from .config import settings  # typical project pattern
except Exception:
    # fallback defaults for local dev — replace via .env/config in production
    class _S:
        SECRET_KEY = "change-me"
        ALGORITHM = "HS256"
        ACCESS_TOKEN_EXPIRE_MINUTES = 60
        REFRESH_TOKEN_EXPIRE_DAYS = 7

    settings = _S()


class TokenError(Exception):
    pass


def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    expires = expires_minutes if expires_minutes is not None else getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60)
    exp_ts = _now_ts() + int(expires * 60)
    payload: Dict[str, Any] = {"sub": str(subject), "iat": _now_ts(), "exp": exp_ts}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=getattr(settings, "ALGORITHM", "HS256"))


def create_refresh_token(subject: str, expires_days: Optional[int] = None) -> str:
    days = expires_days if expires_days is not None else getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 7)
    exp_ts = _now_ts() + int(days * 24 * 60 * 60)
    payload: Dict[str, Any] = {"sub": str(subject), "iat": _now_ts(), "exp": exp_ts, "typ": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=getattr(settings, "ALGORITHM", "HS256"))


def decode_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[getattr(settings, "ALGORITHM", "HS256")])
        return payload
    except JWTError as exc:
        raise TokenError("Invalid token") from exc


def get_subject(token: str) -> Optional[str]:
    payload = decode_token(token)
    return payload.get("sub")


def is_token_expired(token: str) -> bool:
    try:
        payload = decode_token(token)
    except TokenError:
        return True
    exp = payload.get("exp")
    if exp is None:
        return False
    return int(datetime.utcnow().timestamp()) >= int(exp)


def verify_token(token: str, require_type: Optional[str] = None) -> Dict[str, Any]:
    
    payload = decode_token(token)
    if require_type:
        typ = payload.get("typ")
        if typ != require_type:
            raise TokenError("Invalid token type")
    return payload