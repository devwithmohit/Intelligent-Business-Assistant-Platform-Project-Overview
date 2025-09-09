from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional

from ...services import auth_service
from ...schemas import auth_schemas, user_schemas

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=auth_schemas.TokenResponse)
async def login(form_data: Optional[OAuth2PasswordRequestForm] = Depends(), body: Optional[auth_schemas.LoginRequest] = None):
    """
    Login with email + password.
    Accepts either application/x-www-form-urlencoded (OAuth2PasswordRequestForm)
    or JSON body matching LoginRequest.
    Returns access (and optionally refresh) token.
    """
    # support form or json
    if form_data:
        email = form_data.username
        password = form_data.password
    elif body:
        email = body.email
        password = body.password
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing credentials")

    try:
        token = await auth_service.login(email=email, password=password)
        return token
    except auth_service.AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed")


@router.post("/register", response_model=auth_schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: auth_schemas.RegisterRequest):
    """
    Register a new user. If backend returns tokens on register, they will be returned.
    """
    try:
        token_or_user = await auth_service.register(payload)
        # auth_service.register may return TokenResponse or user; try to normalize in service.
        return token_or_user
    except auth_service.AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed")


@router.post("/refresh", response_model=auth_schemas.TokenResponse)
async def refresh(payload: auth_schemas.RefreshRequest):
    """
    Refresh access token using a refresh token.
    """
    try:
        token = await auth_service.refresh_token(payload.refresh_token)
        return token
    except auth_service.AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token refresh failed")


@router.get("/me", response_model=user_schemas.UserRead)
async def me(current_user=Depends(auth_service.get_current_user)):
    """
    Return current authenticated user. Dependency raises if not authenticated.
    """
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return current_user