from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models import User


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def authenticate(db: AsyncSession, username: str, password: str) -> User | None:
    user = await get_user_by_username(db, username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def ensure_initial_user(db: AsyncSession, username: str, password: str) -> None:
    existing = await get_user_by_username(db, username)
    if existing is not None:
        return
    user = User(username=username, password_hash=hash_password(password), display_name=username)
    db.add(user)
    await db.commit()
