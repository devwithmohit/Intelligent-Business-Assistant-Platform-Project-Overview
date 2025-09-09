import os
import sys
import asyncio


HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(HERE)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from core import database
from services import user_service, auth_service
from schemas import user_schemas

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password123")
TEST_EMAIL = os.getenv("TEST_EMAIL", "user@example.com")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "password123")


async def create_if_missing(email: str, password: str, name: str = ""):
    existing = await user_service.get_user_by_email(email)
    if existing:
        print(f"user exists: {email} (id={getattr(existing, 'id', None)})")
        return existing

    hashed = auth_service.get_password_hash(password)
    user_in = user_schemas.UserCreate(name=name or email.split("@")[0], email=email, password=hashed)
    created = await user_service.create_user(user_in)
    print(f"created user: {email} (id={getattr(created, 'id', None)})")
    return created


async def main():
    # create tables for local dev if needed
    try:
        database.init_db(create_tables=True)
    except Exception as e:
        print("init_db warning:", e)

    # create admin and test users
    await create_if_missing(ADMIN_EMAIL, ADMIN_PASSWORD, name="admin")
    await create_if_missing(TEST_EMAIL, TEST_PASSWORD, name="testuser")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("Seeding complete.")
    except Exception as e:
        print("Seeding failed:", e)
        sys.exit(1)