from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import (
    COOKIE_NAME,
    RequestContext,
    get_request_context,
    require_family_admin,
    require_system_admin,
)
from app.core.db import get_db  # re-exported for convenience
from app.models import User

__all__ = [
    "COOKIE_NAME",
    "RequestContext",
    "get_db",
    "get_current_user",
    "get_request_context",
    "require_family_admin",
    "require_system_admin",
]


async def get_current_user(
    context: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
) -> User:
    # get_request_context already verifies the user and current membership.
    # Loading by UUID again keeps the public dependency's return type stable.
    user = await db.get(User, context.user_id)
    assert user is not None
    return user
