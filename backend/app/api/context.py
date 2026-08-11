import uuid

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.family_scope import RequestContext, bind_request_context
from app.core.security import decode_access_token
from app.models import FamilyMembership, User

COOKIE_NAME = "wp_session"


async def get_request_context(
    wp_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    x_family_id: uuid.UUID | None = Header(default=None, alias="X-Family-ID"),
    db: AsyncSession = Depends(get_db),
) -> RequestContext:
    if wp_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    claims = decode_access_token(wp_session)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")

    user = await db.get(User, claims.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")

    family_id = x_family_id or claims.active_family_id
    membership = (
        await db.execute(
            select(FamilyMembership).where(
                FamilyMembership.user_id == user.id,
                FamilyMembership.family_id == family_id,
                FamilyMembership.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="family_access_denied")

    context = RequestContext(
        user_id=user.id,
        family_id=membership.family_id,
        role=membership.role,
        token_jti=claims.jti,
    )
    bind_request_context(db, context)
    return context


async def require_family_admin(
    context: RequestContext = Depends(get_request_context),
) -> RequestContext:
    if context.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="family_admin_required")
    return context


async def require_system_admin(
    context: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
) -> RequestContext:
    user = await db.get(User, context.user_id)
    if user is None or not user.is_system_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="system_admin_required")
    return context
