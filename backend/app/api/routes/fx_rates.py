from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.fx_rate import FXRateRead, FXRateSetRequest
from app.services import valuation_service

router = APIRouter(prefix="/api/fx-rates", tags=["fx-rates"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[FXRateRead])
async def list_fx_rates(db: AsyncSession = Depends(get_db)):
    return await valuation_service.list_latest_fx_rates(db)


@router.post("", response_model=FXRateRead)
async def set_fx_rate(payload: FXRateSetRequest, db: AsyncSession = Depends(get_db)):
    return await valuation_service.set_fx_rate(
        db, payload.base_currency, payload.quote_currency, payload.rate, payload.as_of
    )
