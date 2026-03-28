from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ...services import user_service, auth_service
from ...schemas import user_schemas

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/", response_model=List[user_schemas.UserRead])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user=Depends(auth_service.get_current_user),
):
    """
    List users (requires authentication).
    Pagination via skip/limit.
    """
    try:
        users = await user_service.get_users(skip=skip, limit=limit)
        return users
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to list users")


@router.get("/{user_id}", response_model=user_schemas.UserRead)
async def get_user(user_id: int, current_user=Depends(auth_service.get_current_user)):
    """
    Get a single user by ID (requires authentication).
    """
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=user_schemas.UserRead)
async def update_user(
    user_id: int,
    payload: user_schemas.UserUpdate,
    current_user=Depends(auth_service.get_current_user),
):
    """
    Update user fields. Allowed for the user themself or admins.
    """
    # permission check: allow if updating own account or admin
    is_admin = getattr(current_user, "is_admin", False)
    if (getattr(current_user, "id", None) != user_id) and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this user")

    if payload.is_admin is True and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can grant admin privileges",
        )

    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        updated = await user_service.update_user(user_id, payload)
        return updated
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, current_user=Depends(auth_service.get_current_user)):
    """
    Delete a user. Allowed for the user themself or admins.
    """
    is_admin = getattr(current_user, "is_admin", False)
    if (getattr(current_user, "id", None) != user_id) and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this user")

    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        await user_service.delete_user(user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user")
