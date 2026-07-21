from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db  # re-exported for convenience
from app.core.security import decode_access_token
from app.models import User
from app.services.auth_service import get_user_by_username

COOKIE_NAME = "wp_session"

__all__ = ["COOKIE_NAME", "get_db", "get_current_user"]


async def get_current_user(
    wp_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> User:
    if wp_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    username = decode_access_token(wp_session)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    user = await get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")
    return user
