import asyncio
import json
import logging
from typing import Any, Dict, Optional

import aiohttp  # type: ignore

logger = logging.getLogger(__name__)

# optional Google oauth helpers (used by some integration clients)
try:
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
except Exception:  # pragma: no cover - optional deps
    Credentials = None  # type: ignore
    InstalledAppFlow = None  # type: ignore
    Request = None  # type: ignore

# optional JWT helpers (python-jose)
try:
    from jose import jwt as jose_jwt  # type: ignore
    from jose.exceptions import JWTError  # type: ignore
except Exception:  # pragma: no cover - optional deps
    jose_jwt = None  # type: ignore
    JWTError = Exception  # type: ignore


# ---------- Google / InstalledAppFlow helpers --------------------------------


async def run_google_local_server_flow(
    client_secrets_path: str,
    scopes: list[str],
    token_path: Optional[str] = None,
    host: str = "localhost",
    port: int = 0,
    open_browser: bool = True,
) -> "Credentials":
    """
    Run google_auth_oauthlib InstalledAppFlow.run_local_server in a threadpool and
    optionally persist the resulting credentials JSON to token_path.

    Returns google.oauth2.credentials.Credentials instance.

    Note: this requires google-auth-oauthlib on the environment.
    """
    if InstalledAppFlow is None:
        raise RuntimeError("google-auth-oauthlib not installed")

    loop = asyncio.get_running_loop()

    def _flow():
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes=scopes)
        creds = flow.run_local_server(host=host, port=port, open_browser=open_browser)
        if token_path and creds:
            try:
                with open(token_path, "w", encoding="utf-8") as fh:
                    fh.write(creds.to_json())
            except Exception:
                logger.debug("Failed to persist google token to %s", token_path, exc_info=True)
        return creds

    creds = await loop.run_in_executor(None, _flow)
    return creds


async def load_google_credentials_from_file(token_path: str, scopes: Optional[list[str]] = None) -> Optional["Credentials"]:
    """
    Load Credentials from a token JSON file and refresh if expired (sync refresh executed in threadpool).
    Returns Credentials or None if not available.
    """
    if Credentials is None:
        raise RuntimeError("google-auth library not installed")

    loop = asyncio.get_running_loop()

    def _load():
        try:
            with open(token_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            creds = Credentials.from_authorized_user_info(data, scopes=scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds
        except Exception:
            logger.debug("Failed to load/refresh google credentials from %s", token_path, exc_info=True)
            return None

    creds = await loop.run_in_executor(None, _load)
    return creds


# ---------- Generic OAuth2 helpers (token exchange / introspection) ---------


async def exchange_oauth2_code_for_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Perform OAuth2 token exchange (authorization code -> token) using aiohttp.
    Returns the token response JSON.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if redirect_uri:
        data["redirect_uri"] = redirect_uri
    if extra_params:
        data.update(extra_params)

    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.post(token_url, data=data, timeout=timeout) as resp:
                text = await resp.text()
                try:
                    return await resp.json()
                except Exception:
                    # fallback to raw text in dict
                    return {"status": resp.status, "text": text}
        except Exception as exc:
            logger.exception("OAuth2 token exchange failed")
            raise


async def introspect_oauth2_token(
    introspection_url: str,
    token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Call OAuth2 token introspection endpoint per RFC7662.
    Returns the introspection response JSON.
    """
    data = {"token": token}
    headers = {}
    auth = None
    if client_id and client_secret:
        # prefer HTTP Basic auth
        auth = aiohttp.BasicAuth(login=client_id, password=client_secret)
    async with aiohttp.ClientSession(auth=auth) as sess:
        try:
            async with sess.post(introspection_url, data=data, timeout=timeout, headers=headers) as resp:
                return await resp.json()
        except Exception:
            logger.exception("Token introspection failed for %s", introspection_url)
            raise


# ---------- JWT / JWK helpers ----------------------------------------------


async def fetch_jwks(jwks_uri: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Fetch JWKS (JSON Web Key Set) from jwks_uri.
    """
    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.get(jwks_uri, timeout=timeout) as resp:
                return await resp.json()
        except Exception:
            logger.exception("Failed to fetch JWKS from %s", jwks_uri)
            raise


def _select_jwk_for_token(jwks: Dict[str, Any], token: str) -> Optional[Dict[str, Any]]:
    """
    Helper: pick JWK from JWKS set by matching 'kid' in token header.
    """
    if jose_jwt is None:
        return None
    try:
        header = jose_jwt.get_unverified_header(token)
        kid = header.get("kid")
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
    except Exception:
        logger.debug("Failed to inspect token header for kid", exc_info=True)
    return None


async def verify_jwt_token(
    token: str,
    jwks_uri: Optional[str] = None,
    audience: Optional[str] = None,
    issuer: Optional[str] = None,
    algorithms: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    Verify a JWT using JWKS (if jwks_uri provided) or using python-jose's default flow.
    Returns decoded claims on success, raises JWTError (or ValueError) on failure.

    - jwks_uri: URL to fetch JWKS, used to obtain public key for token verification.
    - audience: expected aud value (optional).
    - issuer: expected iss value (optional).
    """
    if jose_jwt is None:
        raise RuntimeError("python-jose not installed; cannot verify JWTs")

    algorithms = algorithms or ["RS256"]
    if jwks_uri:
        jwks = await fetch_jwks(jwks_uri)
        jwk_key = _select_jwk_for_token(jwks, token)
        if not jwk_key:
            raise JWTError("no matching JWK found for token")
        # python-jose accepts a JWK dict as key for verify
        try:
            claims = jose_jwt.decode(token, jwk_key, algorithms=algorithms, audience=audience, issuer=issuer)
            return claims
        except JWTError:
            logger.exception("JWT verification with JWKS failed")
            raise
    # fallback: attempt decode with token (may raise)
    try:
        claims = jose_jwt.decode(token, key=None, algorithms=algorithms, audience=audience, issuer=issuer, options={"verify_signature": False})
        # Note: when no key provided we only return unverified claims
        return claims
    except JWTError:
        logger.exception("JWT decode failed")
        raise


# ----------------------- convenience aliases --------------------------------


async def validate_access_token_with_userinfo(userinfo_endpoint: str, token: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Validate an access token by calling an OIDC /userinfo endpoint.
    Returns the userinfo JSON on success (status 200), raises otherwise.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.get(userinfo_endpoint, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"validation failed: {resp.status} {text}")
                return await resp.json()
        except Exception:
            logger.exception("Userinfo validation failed for %s", userinfo_endpoint)
            raise