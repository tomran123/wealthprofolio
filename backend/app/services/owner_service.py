import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import family_scoped_get
from app.models import Owner
from app.schemas.owner import OwnerCreate, OwnerUpdate


async def list_owners(db: AsyncSession) -> list[Owner]:
    result = await db.execute(select(Owner).order_by(Owner.display_order, Owner.name))
    return list(result.scalars().all())


async def search_owners(db: AsyncSession, query: str) -> list[Owner]:
    stmt = select(Owner).where(Owner.name.ilike(f"%{query}%")).limit(20)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_owner(db: AsyncSession, owner_id: uuid.UUID) -> Owner | None:
    return await family_scoped_get(db, Owner, owner_id)


async def create_owner(
    db: AsyncSession,
    data: OwnerCreate,
    *,
    record_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Owner:
    values = data.model_dump()
    if record_id is not None:
        values["id"] = record_id
    owner = Owner(**values)
    db.add(owner)
    if commit:
        await db.commit()
        await db.refresh(owner)
    else:
        await db.flush()
    return owner


async def update_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
    data: OwnerUpdate,
    *,
    commit: bool = True,
) -> Owner | None:
    owner = await family_scoped_get(db, Owner, owner_id)
    if owner is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(owner, field, value)
    if commit:
        await db.commit()
        await db.refresh(owner)
    else:
        await db.flush()
    return owner


async def delete_owner(db: AsyncSession, owner_id: uuid.UUID, *, commit: bool = True) -> bool:
    owner = await family_scoped_get(db, Owner, owner_id)
    if owner is None:
        return False
    await db.delete(owner)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True
