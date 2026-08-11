from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ValuationSnapshot
from app.services import portfolio_service


async def create_valuation_snapshot(
    db: AsyncSession,
    base_currency: str,
    refresh_result: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> ValuationSnapshot:
    valuations = await portfolio_service.load_portfolio_valuations(db, base_currency)
    summary = portfolio_service.summarize_valuations(valuations, base_currency)
    allocations: dict[str, list[dict[str, Any]]] = {}
    for dimension in portfolio_service.DIMENSIONS:
        aggregate = portfolio_service.aggregate_valuations(valuations, dimension, base_currency)
        allocations[dimension] = [
            {
                "key": group["key"],
                "label": group["label"],
                "value_base": str(group["value_base"]),
                "percentage": group["percentage"],
                "holdings_count": group["holdings_count"],
            }
            for group in aggregate["groups"]
        ]

    snapshot = ValuationSnapshot(
        base_currency=base_currency,
        total_assets=summary["total_assets"],
        total_liabilities=summary["total_liabilities"],
        net_worth=summary["net_worth"],
        allocation_json=allocations,
        refresh_result_json=refresh_result or {},
    )
    db.add(snapshot)
    if commit:
        await db.commit()
        await db.refresh(snapshot)
    else:
        await db.flush()
    return snapshot


async def list_valuation_snapshots(
    db: AsyncSession, offset: int = 0, limit: int = 100
) -> tuple[list[ValuationSnapshot], int]:
    total = int((await db.execute(select(func.count()).select_from(ValuationSnapshot))).scalar_one())
    stmt = (
        select(ValuationSnapshot)
        .order_by(ValuationSnapshot.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, total


async def get_latest_valuation_snapshot(db: AsyncSession) -> ValuationSnapshot | None:
    stmt = select(ValuationSnapshot).order_by(ValuationSnapshot.created_at.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()
