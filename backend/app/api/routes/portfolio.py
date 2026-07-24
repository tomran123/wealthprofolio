from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.schemas.portfolio import (
    AggregateResponse,
    PortfolioSummary,
    RefreshResultRead,
    ValuationSnapshotPage,
    ValuationSnapshotRead,
)
from app.services import (
    portfolio_service,
    price_refresh_service,
    settings_service,
    valuation_snapshot_service,
    transaction_service,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"], dependencies=[Depends(get_current_user)])
settings = get_settings()


@router.get("/summary", response_model=PortfolioSummary)
async def get_summary(db: AsyncSession = Depends(get_db)):
    base_currency = await settings_service.get_base_currency(db, settings.default_base_currency)
    return await portfolio_service.get_portfolio_summary(db, base_currency)


@router.get("/aggregate", response_model=AggregateResponse)
async def aggregate(
    dimension: str = Query(default="instrument"),
    db: AsyncSession = Depends(get_db),
):
    if dimension not in portfolio_service.DIMENSIONS:
        raise HTTPException(status_code=400, detail="invalid_dimension")
    base_currency = await settings_service.get_base_currency(db, settings.default_base_currency)
    return await portfolio_service.aggregate_portfolio(db, dimension, base_currency)


def _snapshot_schema(snapshot) -> ValuationSnapshotRead:
    return ValuationSnapshotRead(
        id=str(snapshot.id),
        created_at=snapshot.created_at.isoformat(),
        base_currency=snapshot.base_currency,
        total_assets=snapshot.total_assets,
        total_liabilities=snapshot.total_liabilities,
        net_worth=snapshot.net_worth,
        allocation_json=snapshot.allocation_json,
        refresh_result_json=snapshot.refresh_result_json,
    )


@router.post("/refresh", response_model=RefreshResultRead)
async def refresh_all_prices(db: AsyncSession = Depends(get_db)):
    return await price_refresh_service.refresh_all_prices(db)


@router.get("/snapshots", response_model=ValuationSnapshotPage)
async def list_snapshots(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await valuation_snapshot_service.list_valuation_snapshots(db, offset, limit)
    return ValuationSnapshotPage(
        items=[_snapshot_schema(row) for row in rows], total=total, offset=offset, limit=limit
    )


@router.get("/snapshots/latest", response_model=ValuationSnapshotRead)
async def latest_snapshot(db: AsyncSession = Depends(get_db)):
    snapshot = await valuation_snapshot_service.get_latest_valuation_snapshot(db)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="valuation_snapshot_not_found")
    return _snapshot_schema(snapshot)


@router.post("/recalculate")
async def recalculate_portfolio(db: AsyncSession = Depends(get_db)):
    transaction_count = await transaction_service.recalculate_holdings_from_ledger(db)
    return {"ok": True, "transaction_count": transaction_count}
