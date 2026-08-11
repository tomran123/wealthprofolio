import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
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
IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", max_length=180),
]


@router.put("", response_model=HoldingRead)
async def set_holding_snapshot(
    payload: HoldingSetRequest,
    idempotency_key: IdempotencyKey = None,
    db: AsyncSession = Depends(get_db),
):
    holding = await holding_service.set_holding_snapshot(
        db,
        payload.account_id,
        payload.instrument_id,
        payload.quantity,
        idempotency_key=idempotency_key,
    )
    return holding


@router.post("/from-market-search", response_model=MarketHoldingCreateResult, status_code=status.HTTP_201_CREATED)
async def add_holding_from_market_search(
    payload: MarketHoldingCreateRequest,
    idempotency_key: IdempotencyKey = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await market_instrument_service.add_holding_from_market_search(
            db,
            payload,
            idempotency_key=idempotency_key,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail in {"account_not_found", "instrument_not_found"}:
            code = status.HTTP_404_NOT_FOUND
        elif detail == "idempotency_key_reused_with_different_payload":
            code = status.HTTP_409_CONFLICT
        elif detail == "market_quote_unavailable":
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc


@router.post("/adjust", response_model=HoldingRead)
async def adjust_holding(
    payload: HoldingAdjustRequest,
    idempotency_key: IdempotencyKey = None,
    db: AsyncSession = Depends(get_db),
):
    holding = await holding_service.adjust_holding(
        db,
        payload.account_id,
        payload.instrument_id,
        payload.delta_quantity,
        idempotency_key=idempotency_key,
    )
    return holding


@router.delete("/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(holding_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Holdings are replayable projections and are never physically deleted.
    # Older clients get an explicit deprecation response instead of a generic
    # 500; they should set the quantity to zero, which emits a reconciliation
    # event through the compatibility PUT endpoint.
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="holding_delete_deprecated_use_reconciliation",
    )
