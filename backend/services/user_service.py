import asyncio
import functools
from typing import Any, List, Optional

from ..core import database
from ..models import user_models
from ..schemas import user_schemas

# ...existing code...


def _get_user_model():
    user_model = getattr(user_models, "User", None)
    if user_model is None:
        raise RuntimeError("User model is not implemented yet")
    return user_model


def _get_session():
    """
    Return a sync Session from core.database.SessionLocal.
    Raises RuntimeError if SessionLocal is not available.
    """
    try:
        return database.SessionLocal()
    except Exception as e:
        raise RuntimeError("Could not get DB session factory (SessionLocal) from core.database") from e


def _sync_get_user_by_email(email: str) -> Optional[Any]:
    user_model = _get_user_model()
    db = _get_session()
    try:
        return db.query(user_model).filter(user_model.email == email).first()
    finally:
        db.close()


async def get_user_by_email(email: str) -> Optional[Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(_sync_get_user_by_email, email))


def _sync_get_user_by_id(user_id: int) -> Optional[Any]:
    user_model = _get_user_model()
    db = _get_session()
    try:
        return db.query(user_model).filter(user_model.id == user_id).first()
    finally:
        db.close()


async def get_user_by_id(user_id: int) -> Optional[Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(_sync_get_user_by_id, user_id))


def _sync_get_users(skip: int = 0, limit: int = 100) -> List[Any]:
    user_model = _get_user_model()
    db = _get_session()
    try:
        q = db.query(user_model).order_by(user_model.id).offset(skip).limit(limit)
        return q.all()
    finally:
        db.close()


async def get_users(skip: int = 0, limit: int = 100) -> List[Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(_sync_get_users, skip, limit))


def _sync_create_user(user_in: user_schemas.UserCreate) -> Any:
    user_model = _get_user_model()
    db = _get_session()
    try:
        obj = user_model(**user_in.model_dump())
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


async def create_user(user_in: user_schemas.UserCreate) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(_sync_create_user, user_in))


def _sync_update_user(user_id: int, payload: user_schemas.UserUpdate) -> Optional[Any]:
    user_model = _get_user_model()
    db = _get_session()
    try:
        obj = db.query(user_model).filter(user_model.id == user_id).first()
        if not obj:
            return None
        update_data = payload.model_dump(exclude_unset=True)
        for k, v in update_data.items():
            setattr(obj, k, v)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


async def update_user(user_id: int, payload: user_schemas.UserUpdate) -> Optional[Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(_sync_update_user, user_id, payload))


def _sync_delete_user(user_id: int) -> bool:
    user_model = _get_user_model()
    db = _get_session()
    try:
        obj = db.query(user_model).filter(user_model.id == user_id).first()
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True
    finally:
        db.close()


async def delete_user(user_id: int) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(_sync_delete_user, user_id))

