from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, status

from ..services import auth_service


async def admin_required(current_user=Depends(auth_service.get_current_user)):
    """
    Dependency that ensures the current user is an admin.
    Use: Depends(admin_required)
    Returns the current_user for downstream use.
    """
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


async def owner_or_admin(target_user_id: int, current_user=Depends(auth_service.get_current_user)):
    """
    Dependency to check that the current_user is either the owner (target_user_id)
    or an admin. Intended to be used in path/route dependencies:

    @router.patch("/users/{target_user_id}")
    async def update_user(..., _ = Depends(owner_or_admin)):
        ...

    When used, FastAPI will provide the path param target_user_id automatically.
    Returns current_user on success.
    """
    current_id = getattr(current_user, "id", None)
    if current_id != target_user_id and not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return current_user


def require_scopes(required_scopes: List[str]) -> Callable:
    """
    Factory that returns a dependency checking the current user's scopes/permissions.
    Usage:
      @router.get("/secret")
      async def secret(_ = Depends(require_scopes(["read:secret"]))):
          ...
    The user's scopes may be provided as a list on the user object (attribute 'scopes').
    Returns the current_user on success.
    """
    async def _checker(current_user=Depends(auth_service.get_current_user)):
        user_scopes = getattr(current_user, "scopes", []) or []
        if isinstance(user_scopes, str):
            user_scopes = [user_scopes]
        missing = [s for s in required_scopes if s not in user_scopes]
        if missing:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope")
        return current_user

    return _checker


__all__ = ["admin_required", "owner_or_admin", "require_scopes"]