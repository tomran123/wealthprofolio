import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Holding
from app.models.enums import HoldingSource
from app.services import transaction_service


async def list_holdings_for_account(
    db: AsyncSession,
    account_id: uuid.UUID,
) -> list[Holding]:
    await transaction_service._require_account(db, account_id)
    stmt = (
        select(Holding)
        .where(Holding.account_id == account_id)
        .options(selectinload(Holding.instrument))
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
) -> Holding | None:
    stmt = select(Holding).where(
        Holding.account_id == account_id,
        Holding.instrument_id == instrument_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _projected_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
) -> Holding:
    holding = await get_holding(db, account_id, instrument_id)
    if holding is None:
        raise RuntimeError("holding_projection_missing")
    return holding


async def set_holding_snapshot(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    quantity: Decimal,
    source: HoldingSource = HoldingSource.MANUAL,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
) -> Holding:
    instrument = await transaction_service._require_instrument(db, instrument_id)
    await transaction_service.create_reconciliation_transaction(
        db,
        account_id,
        instrument_id,
        instrument.currency,
        source,
        target_quantity=quantity,
        commit=commit,
        idempotency_key=idempotency_key,
        metadata={"compatibility_command": "PUT /api/holdings"},
    )
    return await _projected_holding(db, account_id, instrument_id)


async def adjust_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    delta_quantity: Decimal,
    source: HoldingSource = HoldingSource.MANUAL,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
) -> Holding:
    instrument = await transaction_service._require_instrument(db, instrument_id)
    await transaction_service.create_reconciliation_transaction(
        db,
        account_id,
        instrument_id,
        instrument.currency,
        source,
        delta_quantity=delta_quantity,
        commit=commit,
        idempotency_key=idempotency_key,
        metadata={"compatibility_command": "POST /api/holdings/adjust"},
    )
    return await _projected_holding(db, account_id, instrument_id)


async def reconcile_holding_to_zero(
    db: AsyncSession,
    holding_id: uuid.UUID,
    source: HoldingSource = HoldingSource.AGENT,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
) -> Holding:
    holding = (
        await db.execute(select(Holding).where(Holding.id == holding_id))
    ).scalar_one_or_none()
    if holding is None:
        raise ValueError("holding_not_found")
    instrument = await transaction_service._require_instrument(db, holding.instrument_id)
    await transaction_service.create_reconciliation_transaction(
        db,
        holding.account_id,
        holding.instrument_id,
        instrument.currency,
        source,
        target_quantity=Decimal("0"),
        commit=commit,
        idempotency_key=idempotency_key,
        metadata={"compatibility_command": "agent delete_holding"},
        note="Reconciled to zero instead of deleting the projection",
    )
    return await _projected_holding(db, holding.account_id, holding.instrument_id)


async def delete_holding(
    db: AsyncSession,
    holding_id: uuid.UUID,
    *,
    commit: bool = True,
) -> bool:
    raise ValueError("holding_delete_deprecated")
