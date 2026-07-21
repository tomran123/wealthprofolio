import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExposureGroup
from app.schemas.exposure_group import ExposureGroupCreate, ExposureGroupUpdate


async def list_exposure_groups(db: AsyncSession) -> list[ExposureGroup]:
    result = await db.execute(select(ExposureGroup).order_by(ExposureGroup.name))
    return list(result.scalars().all())


async def create_exposure_group(db: AsyncSession, data: ExposureGroupCreate) -> ExposureGroup:
    group = ExposureGroup(**data.model_dump())
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def update_exposure_group(
    db: AsyncSession, group_id: uuid.UUID, data: ExposureGroupUpdate
) -> ExposureGroup | None:
    group = await db.get(ExposureGroup, group_id)
    if group is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    await db.refresh(group)
    return group


async def delete_exposure_group(db: AsyncSession, group_id: uuid.UUID) -> bool:
    group = await db.get(ExposureGroup, group_id)
    if group is None:
        return False
    await db.delete(group)
    await db.commit()
    return True
