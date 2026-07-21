from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.schemas.portfolio import AggregateResponse, PortfolioSummary
from app.services import portfolio_service, settings_service

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
