import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.holding import (
    HoldingAdjustRequest,
    HoldingRead,
    HoldingSetRequest,
    MarketHoldingCreateRequest,
    MarketHoldingCreateResult,
)
from app.services import holding_service, market_instrument_service

router = APIRouter(prefix="/api/holdings", tags=["holdings"], dependencies=[Depends(get_current_user)])


@router.put("", response_model=HoldingRead)
async def set_holding_snapshot(payload: HoldingSetRequest, db: AsyncSession = Depends(get_db)):
    holding = await holding_service.set_holding_snapshot(
        db, payload.account_id, payload.instrument_id, payload.quantity
    )
    return holding


@router.post("/from-market-search", response_model=MarketHoldingCreateResult, status_code=status.HTTP_201_CREATED)
async def add_holding_from_market_search(
    payload: MarketHoldingCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await market_instrument_service.add_holding_from_market_search(db, payload)
    except ValueError as exc:
        detail = str(exc)
        if detail in {"account_not_found", "instrument_not_found"}:
            code = status.HTTP_404_NOT_FOUND
        elif detail == "market_quote_unavailable":
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc


@router.post("/adjust", response_model=HoldingRead)
async def adjust_holding(payload: HoldingAdjustRequest, db: AsyncSession = Depends(get_db)):
    holding = await holding_service.adjust_holding(
        db, payload.account_id, payload.instrument_id, payload.delta_quantity
    )
    return holding


@router.delete("/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(holding_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await holding_service.delete_holding(db, holding_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="holding_not_found")
