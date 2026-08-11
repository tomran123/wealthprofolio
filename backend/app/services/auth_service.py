from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models import Family, FamilyMembership, User

DEFAULT_FAMILY_SLUG = "default-family"


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


async def get_default_membership(
    db: AsyncSession,
    user_id,
) -> FamilyMembership | None:
    stmt = (
        select(FamilyMembership)
        .where(
            FamilyMembership.user_id == user_id,
            FamilyMembership.is_active.is_(True),
        )
        .order_by(FamilyMembership.created_at, FamilyMembership.id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def ensure_initial_user(db: AsyncSession, username: str, password: str) -> None:
    family = (
        await db.execute(select(Family).where(Family.slug == DEFAULT_FAMILY_SLUG))
    ).scalar_one_or_none()
    if family is None:
        family = Family(name="Default Family", slug=DEFAULT_FAMILY_SLUG)
        db.add(family)
        await db.flush()

    existing = await get_user_by_username(db, username)
    if existing is None:
        existing = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            is_system_admin=True,
        )
        db.add(existing)
        await db.flush()
    membership = (
        await db.execute(
            select(FamilyMembership).where(
                FamilyMembership.family_id == family.id,
                FamilyMembership.user_id == existing.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(
            FamilyMembership(
                family_id=family.id,
                user_id=existing.id,
                role="admin",
                is_active=True,
            )
        )
    await db.commit()
