import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import COOKIE_NAME, RequestContext, get_current_user, get_db, get_request_context
from app.core.config import get_settings
from app.core.rate_limit import login_rate_limiter
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import LoginRequest, UserRead
from app.services.auth_service import authenticate, get_default_membership

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> UserRead:
    client_ip = request.client.host if request.client else "unknown"
    client_key = f"{client_ip}:{payload.username.strip().casefold()}"
    # Reserve an attempt atomically before the deliberately expensive bcrypt
    # check.  A successful login clears the window.
    if not await login_rate_limiter.consume(client_key):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts")

    user = await authenticate(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    await login_rate_limiter.reset(client_key)
    membership = await get_default_membership(db, user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="family_membership_required")
    token = create_access_token(user.id, membership.family_id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key="wp_csrf",
        value=secrets.token_urlsafe(32),
        httponly=False,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return UserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        active_family_id=membership.family_id,
        role=membership.role,
    )


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie("wp_csrf", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserRead)
async def me(
    user: User = Depends(get_current_user),
    context: RequestContext = Depends(get_request_context),
) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        active_family_id=context.family_id,
        role=context.role,
    )
