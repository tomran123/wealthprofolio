from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import COOKIE_NAME, get_current_user, get_db
from app.core.config import get_settings
from app.core.rate_limit import login_rate_limiter
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import LoginRequest, UserRead
from app.services.auth_service import authenticate

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> UserRead:
    client_key = request.client.host if request.client else "unknown"
    if not login_rate_limiter.is_allowed(client_key):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts")

    user = await authenticate(db, payload.username, payload.password)
    if user is None:
        login_rate_limiter.record_attempt(client_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    login_rate_limiter.reset(client_key)
    token = create_access_token(user.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return UserRead(username=user.username, display_name=user.display_name)


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead(username=user.username, display_name=user.display_name)
