import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.instrument import (
    InstrumentCreate,
    InstrumentRead,
    InstrumentUpdate,
    ManualValuationCreate,
    PriceSnapshotRead,
)
from app.services import instrument_service, valuation_service

router = APIRouter(prefix="/api/instruments", tags=["instruments"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[InstrumentRead])
async def list_instruments(q: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    if q:
        return await instrument_service.search_instruments(db, q)
    return await instrument_service.list_instruments(db)


@router.get("/{instrument_id}", response_model=InstrumentRead)
async def get_instrument(instrument_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    instrument = await instrument_service.get_instrument(db, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument_not_found")
    return instrument


@router.post("", response_model=InstrumentRead, status_code=status.HTTP_201_CREATED)
async def create_instrument(payload: InstrumentCreate, db: AsyncSession = Depends(get_db)):
    return await instrument_service.create_instrument(db, payload)


@router.patch("/{instrument_id}", response_model=InstrumentRead)
async def update_instrument(instrument_id: uuid.UUID, payload: InstrumentUpdate, db: AsyncSession = Depends(get_db)):
    instrument = await instrument_service.update_instrument(db, instrument_id, payload)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument_not_found")
    return instrument


@router.delete("/{instrument_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instrument(instrument_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await instrument_service.delete_instrument(db, instrument_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="instrument_not_found")


@router.post("/{instrument_id}/valuation", response_model=PriceSnapshotRead, status_code=status.HTTP_201_CREATED)
async def set_manual_valuation(instrument_id: uuid.UUID, payload: ManualValuationCreate, db: AsyncSession = Depends(get_db)):
    instrument = await instrument_service.get_instrument(db, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument_not_found")
    snapshot = await valuation_service.set_manual_valuation(
        db, instrument_id, payload.price, payload.currency, payload.as_of, payload.note
    )
    return PriceSnapshotRead(
        price=snapshot.price,
        currency=snapshot.currency,
        as_of=snapshot.as_of,
        source_provider=snapshot.source_provider,
        quote_status=snapshot.quote_status.value,
        note=snapshot.note,
    )


@router.get("/{instrument_id}/price-history", response_model=list[PriceSnapshotRead])
async def get_price_history(instrument_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    history = await valuation_service.list_price_history(db, instrument_id)
    return [
        PriceSnapshotRead(
            price=h.price,
            currency=h.currency,
            as_of=h.as_of,
            source_provider=h.source_provider,
            quote_status=h.quote_status.value,
            note=h.note,
        )
        for h in history
    ]
