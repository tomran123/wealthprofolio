import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Institution
from app.schemas.institution import InstitutionCreate, InstitutionUpdate


async def list_institutions(db: AsyncSession) -> list[Institution]:
    result = await db.execute(select(Institution).order_by(Institution.name))
    return list(result.scalars().all())


async def search_institutions(db: AsyncSession, query: str) -> list[Institution]:
    stmt = select(Institution).where(Institution.name.ilike(f"%{query}%")).limit(20)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_institution(db: AsyncSession, institution_id: uuid.UUID) -> Institution | None:
    return await db.get(Institution, institution_id)


async def create_institution(
    db: AsyncSession,
    data: InstitutionCreate,
    *,
    record_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Institution:
    values = data.model_dump()
    if record_id is not None:
        values["id"] = record_id
    institution = Institution(**values)
    db.add(institution)
    if commit:
        await db.commit()
        await db.refresh(institution)
    else:
        await db.flush()
    return institution


async def update_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    data: InstitutionUpdate,
    *,
    commit: bool = True,
) -> Institution | None:
    institution = await db.get(Institution, institution_id)
    if institution is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(institution, field, value)
    if commit:
        await db.commit()
        await db.refresh(institution)
    else:
        await db.flush()
    return institution


async def delete_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    commit: bool = True,
) -> bool:
    institution = await db.get(Institution, institution_id)
    if institution is None:
        return False
    await db.delete(institution)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True
