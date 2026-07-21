import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FXRateSnapshot, PriceSnapshot
from app.models.enums import QuoteStatus


async def get_latest_price(db: AsyncSession, instrument_id: uuid.UUID) -> PriceSnapshot | None:
    stmt = (
        select(PriceSnapshot)
        .where(PriceSnapshot.instrument_id == instrument_id)
        .order_by(PriceSnapshot.as_of.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_price_history(db: AsyncSession, instrument_id: uuid.UUID, limit: int = 30) -> list[PriceSnapshot]:
    stmt = (
        select(PriceSnapshot)
        .where(PriceSnapshot.instrument_id == instrument_id)
        .order_by(PriceSnapshot.as_of.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def set_manual_valuation(
    db: AsyncSession,
    instrument_id: uuid.UUID,
    price: Decimal,
    currency: str,
    as_of: datetime | None = None,
    note: str | None = None,
) -> PriceSnapshot:
    now = datetime.now(timezone.utc)
    snapshot = PriceSnapshot(
        instrument_id=instrument_id,
        price=price,
        currency=currency,
        as_of=as_of or now,
        fetched_at=now,
        source_provider="manual",
        quote_status=QuoteStatus.MANUAL,
        note=note,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_latest_fx_rate(db: AsyncSession, base_currency: str, quote_currency: str) -> Decimal | None:
    if base_currency == quote_currency:
        return Decimal("1")

    stmt = (
        select(FXRateSnapshot)
        .where(
            FXRateSnapshot.base_currency == base_currency,
            FXRateSnapshot.quote_currency == quote_currency,
        )
        .order_by(FXRateSnapshot.as_of.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    direct = result.scalar_one_or_none()
    if direct is not None:
        return direct.rate

    stmt_inverse = (
        select(FXRateSnapshot)
        .where(
            FXRateSnapshot.base_currency == quote_currency,
            FXRateSnapshot.quote_currency == base_currency,
        )
        .order_by(FXRateSnapshot.as_of.desc())
        .limit(1)
    )
    result_inverse = await db.execute(stmt_inverse)
    inverse = result_inverse.scalar_one_or_none()
    if inverse is not None and inverse.rate != 0:
        return Decimal("1") / inverse.rate

    return None


async def set_fx_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    rate: Decimal,
    as_of: datetime | None = None,
    source_provider: str = "manual",
) -> FXRateSnapshot:
    now = datetime.now(timezone.utc)
    snapshot = FXRateSnapshot(
        base_currency=base_currency.upper(),
        quote_currency=quote_currency.upper(),
        rate=rate,
        as_of=as_of or now,
        fetched_at=now,
        source_provider=source_provider,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def list_latest_fx_rates(db: AsyncSession) -> list[FXRateSnapshot]:
    stmt = select(FXRateSnapshot).order_by(FXRateSnapshot.as_of.desc())
    result = await db.execute(stmt)
    seen: set[tuple[str, str]] = set()
    latest: list[FXRateSnapshot] = []
    for row in result.scalars().all():
        pair = (row.base_currency, row.quote_currency)
        if pair in seen:
            continue
        seen.add(pair)
        latest.append(row)
    return latest
