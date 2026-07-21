import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    return await db.get(Owner, owner_id)


async def create_owner(db: AsyncSession, data: OwnerCreate) -> Owner:
    owner = Owner(**data.model_dump())
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    return owner


async def update_owner(db: AsyncSession, owner_id: uuid.UUID, data: OwnerUpdate) -> Owner | None:
    owner = await db.get(Owner, owner_id)
    if owner is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(owner, field, value)
    await db.commit()
    await db.refresh(owner)
    return owner


async def delete_owner(db: AsyncSession, owner_id: uuid.UUID) -> bool:
    owner = await db.get(Owner, owner_id)
    if owner is None:
        return False
    await db.delete(owner)
    await db.commit()
    return True
