import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import family_scoped_get
from app.models import ExposureGroup
from app.schemas.exposure_group import ExposureGroupCreate, ExposureGroupUpdate


async def list_exposure_groups(db: AsyncSession) -> list[ExposureGroup]:
    result = await db.execute(select(ExposureGroup).order_by(ExposureGroup.name))
    return list(result.scalars().all())


async def create_exposure_group(
    db: AsyncSession,
    data: ExposureGroupCreate,
    *,
    record_id: uuid.UUID | None = None,
    commit: bool = True,
) -> ExposureGroup:
    values = data.model_dump()
    if record_id is not None:
        values["id"] = record_id
    group = ExposureGroup(**values)
    db.add(group)
    if commit:
        await db.commit()
        await db.refresh(group)
    else:
        await db.flush()
    return group


async def update_exposure_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    data: ExposureGroupUpdate,
    *,
    commit: bool = True,
) -> ExposureGroup | None:
    group = await family_scoped_get(db, ExposureGroup, group_id)
    if group is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    if commit:
        await db.commit()
        await db.refresh(group)
    else:
        await db.flush()
    return group


async def delete_exposure_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    *,
    commit: bool = True,
) -> bool:
    group = await family_scoped_get(db, ExposureGroup, group_id)
    if group is None:
        return False
    await db.delete(group)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True
