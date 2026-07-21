import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Holding
from app.models.enums import HoldingSource


async def list_holdings_for_account(db: AsyncSession, account_id: uuid.UUID) -> list[Holding]:
    stmt = (
        select(Holding)
        .where(Holding.account_id == account_id)
        .options(selectinload(Holding.instrument))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_holding(db: AsyncSession, account_id: uuid.UUID, instrument_id: uuid.UUID) -> Holding | None:
    stmt = select(Holding).where(Holding.account_id == account_id, Holding.instrument_id == instrument_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def set_holding_snapshot(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    quantity: Decimal,
    source: HoldingSource = HoldingSource.MANUAL,
) -> Holding:
    holding = await get_holding(db, account_id, instrument_id)
    if holding is None:
        holding = Holding(account_id=account_id, instrument_id=instrument_id, quantity=quantity, source=source)
        db.add(holding)
    else:
        holding.quantity = quantity
        holding.source = source
    await db.commit()
    await db.refresh(holding)
    return holding


async def adjust_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    delta_quantity: Decimal,
    source: HoldingSource = HoldingSource.MANUAL,
) -> Holding:
    holding = await get_holding(db, account_id, instrument_id)
    if holding is None:
        holding = Holding(
            account_id=account_id, instrument_id=instrument_id, quantity=delta_quantity, source=source
        )
        db.add(holding)
    else:
        holding.quantity = holding.quantity + delta_quantity
        holding.source = source
    await db.commit()
    await db.refresh(holding)
    return holding


async def delete_holding(db: AsyncSession, holding_id: uuid.UUID) -> bool:
    holding = await db.get(Holding, holding_id)
    if holding is None:
        return False
    await db.delete(holding)
    await db.commit()
    return True
