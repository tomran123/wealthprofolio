import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.holding import HoldingAdjustRequest, HoldingRead, HoldingSetRequest
from app.services import holding_service

router = APIRouter(prefix="/api/holdings", tags=["holdings"], dependencies=[Depends(get_current_user)])


@router.put("", response_model=HoldingRead)
async def set_holding_snapshot(payload: HoldingSetRequest, db: AsyncSession = Depends(get_db)):
    holding = await holding_service.set_holding_snapshot(
        db, payload.account_id, payload.instrument_id, payload.quantity
    )
    return holding


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
