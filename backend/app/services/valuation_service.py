import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FXRateSnapshot, PriceSnapshot
from app.models.enums import QuoteStatus


def build_fx_snapshot(
    base_currency: str,
    quote_currency: str,
    rate: Decimal,
    as_of: datetime,
    source_provider: str,
    fetched_at: datetime | None = None,
) -> FXRateSnapshot:
    return FXRateSnapshot(
        base_currency=base_currency.upper(),
        quote_currency=quote_currency.upper(),
        rate=rate,
        as_of=as_of,
        fetched_at=fetched_at or datetime.now(timezone.utc),
        source_provider=source_provider,
    )


async def get_latest_price(db: AsyncSession, instrument_id: uuid.UUID) -> PriceSnapshot | None:
    stmt = (
        select(PriceSnapshot)
        .where(PriceSnapshot.instrument_id == instrument_id)
        .order_by(PriceSnapshot.as_of.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_prices(
    db: AsyncSession,
    instrument_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, PriceSnapshot]:
    ids = list(dict.fromkeys(instrument_ids))
    if not ids:
        return {}

    ranked = (
        select(
            PriceSnapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=PriceSnapshot.instrument_id,
                order_by=(PriceSnapshot.as_of.desc(), PriceSnapshot.fetched_at.desc()),
            )
            .label("row_number"),
        )
        .where(PriceSnapshot.instrument_id.in_(ids))
        .subquery()
    )
    stmt = (
        select(PriceSnapshot)
        .join(ranked, PriceSnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.row_number == 1)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {row.instrument_id: row for row in rows}


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
    *,
    commit: bool = True,
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
    if commit:
        await db.commit()
        await db.refresh(snapshot)
    else:
        await db.flush()
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


async def get_latest_fx_rates_for_currencies(
    db: AsyncSession,
    currencies: Iterable[str],
    target_currency: str,
) -> dict[str, Decimal]:
    target = target_currency.upper()
    requested = {currency.upper() for currency in currencies if currency}
    rates: dict[str, Decimal] = {target: Decimal("1")}
    needed = requested - {target}
    if not needed:
        return rates

    ranked = (
        select(
            FXRateSnapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=(FXRateSnapshot.base_currency, FXRateSnapshot.quote_currency),
                order_by=(FXRateSnapshot.as_of.desc(), FXRateSnapshot.fetched_at.desc()),
            )
            .label("row_number"),
        )
        .where(
            or_(
                (FXRateSnapshot.base_currency.in_(needed))
                & (FXRateSnapshot.quote_currency == target),
                (FXRateSnapshot.base_currency == target)
                & (FXRateSnapshot.quote_currency.in_(needed)),
            )
        )
        .subquery()
    )
    stmt = (
        select(FXRateSnapshot)
        .join(ranked, FXRateSnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.row_number == 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    for row in rows:
        if row.quote_currency == target:
            rates[row.base_currency] = row.rate
    for row in rows:
        if (
            row.base_currency == target
            and row.quote_currency not in rates
            and row.rate != 0
        ):
            rates[row.quote_currency] = Decimal("1") / row.rate
    return rates


async def set_fx_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    rate: Decimal,
    as_of: datetime | None = None,
    source_provider: str = "manual",
    *,
    commit: bool = True,
) -> FXRateSnapshot:
    now = datetime.now(timezone.utc)
    snapshot = build_fx_snapshot(
        base_currency,
        quote_currency,
        rate,
        as_of or now,
        source_provider=source_provider,
        fetched_at=now,
    )
    db.add(snapshot)
    if commit:
        await db.commit()
        await db.refresh(snapshot)
    else:
        await db.flush()
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
