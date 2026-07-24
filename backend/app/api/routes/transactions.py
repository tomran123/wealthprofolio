import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Transaction
from app.models.enums import TransactionType
from app.schemas.transaction import (
    BuyTransactionCreate,
    CashTransactionCreate,
    FeeTransactionCreate,
    FXExchangeCreate,
    IncomeTransactionCreate,
    ManualAdjustmentCreate,
    SellTransactionCreate,
    TransactionMetadataUpdate,
    TransactionMutationResult,
    TransactionPage,
    TransactionRead,
    TransactionSummary,
    TransferCreate,
)
from app.services import transaction_service

router = APIRouter(prefix="/api/transactions", tags=["transactions"], dependencies=[Depends(get_current_user)])


def _to_schema(tx: Transaction) -> TransactionRead:
    return TransactionRead(
        id=tx.id,
        created_at=tx.created_at,
        updated_at=tx.updated_at,
        account_id=tx.account_id,
        account_name=tx.account.name,
        instrument_id=tx.instrument_id,
        instrument_name=tx.instrument.name if tx.instrument else None,
        instrument_symbol=tx.instrument.symbol if tx.instrument else None,
        transaction_type=tx.transaction_type,
        quantity=tx.quantity,
        price=tx.price,
        currency=tx.currency,
        amount=tx.amount,
        fee=tx.fee,
        fee_currency=tx.fee_currency,
        trade_date=tx.trade_date,
        executed_at=tx.executed_at,
        settlement_date=tx.settlement_date,
        external_ref=tx.external_ref,
        linked_transaction_id=tx.linked_transaction_id,
        note=tx.note,
        source=tx.source,
        is_reversed=tx.is_reversed,
        reversed_by_id=tx.reversed_by_id,
    )


async def _load_result(db: AsyncSession, rows: list[Transaction]) -> TransactionMutationResult:
    loaded = [await transaction_service.get_transaction(db, row.id) for row in rows]
    return TransactionMutationResult(transactions=[_to_schema(row) for row in loaded if row is not None])


def _http_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    code = 404 if detail.endswith("_not_found") else 409
    return HTTPException(status_code=code, detail=detail)


@router.get("", response_model=TransactionPage)
async def list_transactions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    account_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    rows, total, summary = await transaction_service.list_transactions(
        db, offset, limit, account_id, transaction_type, date_from, date_to, instrument_id
    )
    return TransactionPage(
        items=[_to_schema(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
        summary=TransactionSummary(**summary),
    )


@router.post("/buy", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def buy(payload: BuyTransactionCreate, db: AsyncSession = Depends(get_db)):
    try:
        tx = await transaction_service.create_buy_transaction(db, payload)
        return await _load_result(db, [tx])
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/sell", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def sell(payload: SellTransactionCreate, db: AsyncSession = Depends(get_db)):
    try:
        tx = await transaction_service.create_sell_transaction(db, payload)
        return await _load_result(db, [tx])
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/transfer", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def transfer(payload: TransferCreate, db: AsyncSession = Depends(get_db)):
    try:
        rows = await transaction_service.create_transfer(db, payload)
        return await _load_result(db, list(rows))
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/fx-exchange", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def fx_exchange(payload: FXExchangeCreate, db: AsyncSession = Depends(get_db)):
    try:
        rows = await transaction_service.create_currency_exchange(db, payload)
        return await _load_result(db, list(rows))
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/income", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def income(payload: IncomeTransactionCreate, db: AsyncSession = Depends(get_db)):
    try:
        tx = await transaction_service.create_income_transaction(db, payload)
        return await _load_result(db, [tx])
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/fee", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def fee(payload: FeeTransactionCreate, db: AsyncSession = Depends(get_db)):
    try:
        tx = await transaction_service.create_fee_transaction(db, payload)
        return await _load_result(db, [tx])
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/cash", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def cash(payload: CashTransactionCreate, db: AsyncSession = Depends(get_db)):
    try:
        tx = await transaction_service.create_cash_transaction(db, payload)
        return await _load_result(db, [tx])
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/adjustment", response_model=TransactionMutationResult, status_code=status.HTTP_201_CREATED)
async def adjustment(payload: ManualAdjustmentCreate, db: AsyncSession = Depends(get_db)):
    try:
        tx = await transaction_service.create_manual_adjustment(db, payload)
        return await _load_result(db, [tx])
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.patch("/{transaction_id}/metadata", response_model=TransactionMutationResult)
async def update_transaction_metadata(
    transaction_id: uuid.UUID,
    payload: TransactionMetadataUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await transaction_service.update_transaction_metadata(db, transaction_id, payload)
        return await _load_result(db, rows)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        await transaction_service.delete_transaction(db, transaction_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/{transaction_id}/reverse", response_model=TransactionMutationResult)
async def reverse_transaction(transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        rows = await transaction_service.reverse_transaction(db, transaction_id)
        return await _load_result(db, rows)
    except ValueError as exc:
        raise _http_error(exc) from exc
