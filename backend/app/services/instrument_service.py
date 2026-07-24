import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Instrument
from app.schemas.instrument import InstrumentCreate, InstrumentUpdate


async def list_instruments(db: AsyncSession) -> list[Instrument]:
    stmt = select(Instrument).options(selectinload(Instrument.exposure_group)).order_by(Instrument.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def search_instruments(db: AsyncSession, query: str) -> list[Instrument]:
    like = f"%{query}%"
    stmt = (
        select(Instrument)
        .where((Instrument.name.ilike(like)) | (Instrument.symbol.ilike(like)))
        .options(selectinload(Instrument.exposure_group))
        .limit(20)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_instrument(db: AsyncSession, instrument_id: uuid.UUID) -> Instrument | None:
    return await db.get(Instrument, instrument_id)


async def create_instrument(
    db: AsyncSession,
    data: InstrumentCreate,
    *,
    record_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Instrument:
    values = data.model_dump()
    if record_id is not None:
        values["id"] = record_id
    instrument = Instrument(**values)
    db.add(instrument)
    if commit:
        await db.commit()
        await db.refresh(instrument)
    else:
        await db.flush()
    return instrument


async def update_instrument(
    db: AsyncSession,
    instrument_id: uuid.UUID,
    data: InstrumentUpdate,
    *,
    commit: bool = True,
) -> Instrument | None:
    instrument = await db.get(Instrument, instrument_id)
    if instrument is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(instrument, field, value)
    if commit:
        await db.commit()
        await db.refresh(instrument)
    else:
        await db.flush()
    return instrument


async def delete_instrument(
    db: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    commit: bool = True,
) -> bool:
    instrument = await db.get(Instrument, instrument_id)
    if instrument is None:
        return False
    await db.delete(instrument)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True
