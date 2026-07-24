import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Account, Holding, Instrument, Transaction
from app.models.enums import (
    AssetClass,
    HoldingSource,
    MarketRegion,
    PriceSourceType,
    TransactionSource,
    TransactionType,
)
from app.schemas.transaction import (
    BuyTransactionCreate,
    CashTransactionCreate,
    FeeTransactionCreate,
    FXExchangeCreate,
    IncomeTransactionCreate,
    ManualAdjustmentCreate,
    SellTransactionCreate,
    TransactionMetadataUpdate,
    TransferCreate,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _holding_source(source: TransactionSource) -> HoldingSource:
    return HoldingSource(source.value)


async def _finish_write(db: AsyncSession, commit: bool) -> None:
    if commit:
        await db.commit()
    else:
        await db.flush()


async def _require_account(db: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await db.get(Account, account_id)
    if account is None:
        raise ValueError("account_not_found")
    return account


async def _require_instrument(db: AsyncSession, instrument_id: uuid.UUID) -> Instrument:
    instrument = await db.get(Instrument, instrument_id)
    if instrument is None:
        raise ValueError("instrument_not_found")
    return instrument


async def _cash_instrument(db: AsyncSession, currency: str) -> Instrument:
    code = currency.upper()
    stmt = (
        select(Instrument)
        .where(
            Instrument.asset_class == AssetClass.CASH,
            Instrument.currency == code,
            Instrument.symbol == code,
        )
        .limit(1)
    )
    instrument = (await db.execute(stmt)).scalar_one_or_none()
    if instrument is not None:
        return instrument
    instrument = Instrument(
        symbol=code,
        name=f"{code} Cash",
        asset_class=AssetClass.CASH,
        currency=code,
        market=MarketRegion.OTHER,
        price_source_type=PriceSourceType.FX_DERIVED,
    )
    db.add(instrument)
    await db.flush()
    return instrument


async def _adjust_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    delta: Decimal,
    source: TransactionSource,
) -> Holding:
    stmt = (
        select(Holding)
        .where(Holding.account_id == account_id, Holding.instrument_id == instrument_id)
        .with_for_update()
    )
    holding = (await db.execute(stmt)).scalar_one_or_none()
    if holding is None:
        holding = Holding(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=delta,
            source=_holding_source(source),
        )
        db.add(holding)
    else:
        holding.quantity += delta
        holding.source = _holding_source(source)
    await db.flush()
    return holding


async def _adjust_cash(
    db: AsyncSession,
    account_id: uuid.UUID,
    currency: str,
    delta: Decimal,
    source: TransactionSource,
) -> Holding:
    cash = await _cash_instrument(db, currency)
    return await _adjust_holding(db, account_id, cash.id, delta, source)


def _transaction(**kwargs) -> Transaction:
    kwargs.setdefault("id", uuid.uuid4())
    kwargs["currency"] = kwargs["currency"].upper()
    kwargs["fee_currency"] = (kwargs.get("fee_currency") or kwargs["currency"]).upper()
    return Transaction(**kwargs)


async def create_buy_transaction(
    db: AsyncSession,
    data: BuyTransactionCreate,
    *,
    commit: bool = True,
) -> Transaction:
    await _require_account(db, data.account_id)
    await _require_instrument(db, data.instrument_id)
    gross = _money(data.quantity * data.price)
    fee_currency = (data.fee_currency or data.currency).upper()
    tx = _transaction(
        account_id=data.account_id,
        instrument_id=data.instrument_id,
        transaction_type=TransactionType.BUY,
        quantity=data.quantity,
        price=data.price,
        currency=data.currency,
        amount=-gross,
        fee=data.fee,
        fee_currency=fee_currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        settlement_date=data.settlement_date,
        external_ref=data.external_ref,
        note=data.note,
        source=data.source,
    )
    try:
        await _adjust_holding(db, data.account_id, data.instrument_id, data.quantity, data.source)
        await _adjust_cash(db, data.account_id, data.currency, -gross, data.source)
        if data.fee:
            await _adjust_cash(db, data.account_id, fee_currency, -data.fee, data.source)
        db.add(tx)
        await _finish_write(db, commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_sell_transaction(
    db: AsyncSession,
    data: SellTransactionCreate,
    *,
    commit: bool = True,
) -> Transaction:
    await _require_account(db, data.account_id)
    await _require_instrument(db, data.instrument_id)
    existing = await db.execute(
        select(Holding).where(Holding.account_id == data.account_id, Holding.instrument_id == data.instrument_id)
    )
    holding = existing.scalar_one_or_none()
    if holding is None or holding.quantity < data.quantity:
        raise ValueError("insufficient_holding")
    gross = _money(data.quantity * data.price)
    fee_currency = (data.fee_currency or data.currency).upper()
    tx = _transaction(
        account_id=data.account_id,
        instrument_id=data.instrument_id,
        transaction_type=TransactionType.SELL,
        quantity=-data.quantity,
        price=data.price,
        currency=data.currency,
        amount=gross,
        fee=data.fee,
        fee_currency=fee_currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        settlement_date=data.settlement_date,
        external_ref=data.external_ref,
        note=data.note,
        source=data.source,
    )
    try:
        await _adjust_holding(db, data.account_id, data.instrument_id, -data.quantity, data.source)
        await _adjust_cash(db, data.account_id, data.currency, gross, data.source)
        if data.fee:
            await _adjust_cash(db, data.account_id, fee_currency, -data.fee, data.source)
        db.add(tx)
        await _finish_write(db, commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_transfer(
    db: AsyncSession,
    data: TransferCreate,
    *,
    commit: bool = True,
) -> tuple[Transaction, Transaction]:
    await _require_account(db, data.from_account_id)
    await _require_account(db, data.to_account_id)
    await _require_instrument(db, data.instrument_id)
    existing = await db.execute(
        select(Holding).where(
            Holding.account_id == data.from_account_id,
            Holding.instrument_id == data.instrument_id,
        )
    )
    holding = existing.scalar_one_or_none()
    if holding is None or holding.quantity < data.quantity:
        raise ValueError("insufficient_holding")

    out_id, in_id = uuid.uuid4(), uuid.uuid4()
    common = {
        "instrument_id": data.instrument_id,
        "price": None,
        "currency": data.currency,
        "amount": ZERO,
        "fee": ZERO,
        "fee_currency": data.currency,
        "trade_date": data.trade_date,
        "executed_at": data.executed_at,
        "settlement_date": data.settlement_date,
        "external_ref": data.external_ref,
        "note": data.note,
        "source": data.source,
    }
    outgoing = _transaction(
        id=out_id,
        account_id=data.from_account_id,
        transaction_type=TransactionType.TRANSFER_OUT,
        quantity=-data.quantity,
        linked_transaction_id=in_id,
        **common,
    )
    incoming = _transaction(
        id=in_id,
        account_id=data.to_account_id,
        transaction_type=TransactionType.TRANSFER_IN,
        quantity=data.quantity,
        linked_transaction_id=out_id,
        **common,
    )
    try:
        await _adjust_holding(db, data.from_account_id, data.instrument_id, -data.quantity, data.source)
        await _adjust_holding(db, data.to_account_id, data.instrument_id, data.quantity, data.source)
        db.add_all([outgoing, incoming])
        await _finish_write(db, commit)
        return outgoing, incoming
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_currency_exchange(
    db: AsyncSession,
    data: FXExchangeCreate,
    *,
    commit: bool = True,
) -> tuple[Transaction, Transaction]:
    await _require_account(db, data.account_id)
    from_currency, to_currency = data.from_currency.upper(), data.to_currency.upper()
    from_cash = await _cash_instrument(db, from_currency)
    to_cash = await _cash_instrument(db, to_currency)
    fee_currency = (data.fee_currency or from_currency).upper()
    out_id, in_id = uuid.uuid4(), uuid.uuid4()
    rate = data.rate or data.to_amount / data.from_amount
    outgoing = _transaction(
        id=out_id,
        account_id=data.account_id,
        instrument_id=from_cash.id,
        transaction_type=TransactionType.FX_EXCHANGE,
        quantity=-data.from_amount,
        price=rate,
        currency=from_currency,
        amount=-data.from_amount,
        fee=data.fee,
        fee_currency=fee_currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        source=data.source,
        linked_transaction_id=in_id,
    )
    incoming = _transaction(
        id=in_id,
        account_id=data.account_id,
        instrument_id=to_cash.id,
        transaction_type=TransactionType.FX_EXCHANGE,
        quantity=data.to_amount,
        price=rate,
        currency=to_currency,
        amount=data.to_amount,
        fee=ZERO,
        fee_currency=to_currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        source=data.source,
        linked_transaction_id=out_id,
    )
    try:
        await _adjust_holding(db, data.account_id, from_cash.id, -data.from_amount, data.source)
        await _adjust_holding(db, data.account_id, to_cash.id, data.to_amount, data.source)
        if data.fee:
            await _adjust_cash(db, data.account_id, fee_currency, -data.fee, data.source)
        db.add_all([outgoing, incoming])
        await _finish_write(db, commit)
        return outgoing, incoming
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_income_transaction(
    db: AsyncSession,
    data: IncomeTransactionCreate,
    *,
    commit: bool = True,
) -> Transaction:
    await _require_account(db, data.account_id)
    if data.instrument_id:
        await _require_instrument(db, data.instrument_id)
    amount = _money(data.amount)
    tx = _transaction(
        account_id=data.account_id,
        instrument_id=data.instrument_id,
        transaction_type=data.transaction_type,
        quantity=ZERO,
        price=None,
        currency=data.currency,
        amount=amount,
        fee=ZERO,
        fee_currency=data.currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        source=data.source,
    )
    try:
        await _adjust_cash(db, data.account_id, data.currency, amount, data.source)
        db.add(tx)
        await _finish_write(db, commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_fee_transaction(
    db: AsyncSession,
    data: FeeTransactionCreate,
    *,
    commit: bool = True,
) -> Transaction:
    await _require_account(db, data.account_id)
    if data.instrument_id:
        await _require_instrument(db, data.instrument_id)
    amount = _money(data.amount)
    tx = _transaction(
        account_id=data.account_id,
        instrument_id=data.instrument_id,
        transaction_type=TransactionType.FEE,
        quantity=ZERO,
        price=None,
        currency=data.currency,
        amount=-amount,
        fee=ZERO,
        fee_currency=data.currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        source=data.source,
    )
    try:
        await _adjust_cash(db, data.account_id, data.currency, -amount, data.source)
        db.add(tx)
        await _finish_write(db, commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_cash_transaction(
    db: AsyncSession,
    data: CashTransactionCreate,
    *,
    commit: bool = True,
) -> Transaction:
    await _require_account(db, data.account_id)
    cash = await _cash_instrument(db, data.currency)
    signed = data.amount if data.transaction_type == TransactionType.DEPOSIT else -data.amount
    tx = _transaction(
        account_id=data.account_id,
        instrument_id=cash.id,
        transaction_type=data.transaction_type,
        quantity=signed,
        price=Decimal("1"),
        currency=data.currency,
        amount=signed,
        fee=ZERO,
        fee_currency=data.currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        source=data.source,
    )
    try:
        await _adjust_holding(db, data.account_id, cash.id, signed, data.source)
        db.add(tx)
        await _finish_write(db, commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def create_manual_adjustment(
    db: AsyncSession,
    data: ManualAdjustmentCreate,
    *,
    commit: bool = True,
) -> Transaction:
    await _require_account(db, data.account_id)
    await _require_instrument(db, data.instrument_id)
    tx = _transaction(
        account_id=data.account_id,
        instrument_id=data.instrument_id,
        transaction_type=TransactionType.MANUAL_ADJUSTMENT,
        quantity=data.delta_quantity,
        price=None,
        currency=data.currency,
        amount=ZERO,
        fee=ZERO,
        fee_currency=data.currency,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        source=data.source,
    )
    try:
        await _adjust_holding(db, data.account_id, data.instrument_id, data.delta_quantity, data.source)
        db.add(tx)
        await _finish_write(db, commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def _apply_inverse(db: AsyncSession, tx: Transaction) -> None:
    source = tx.source if isinstance(tx.source, TransactionSource) else TransactionSource(str(tx.source))
    if tx.transaction_type in (TransactionType.BUY, TransactionType.SELL):
        if tx.instrument_id:
            await _adjust_holding(db, tx.account_id, tx.instrument_id, -tx.quantity, source)
        await _adjust_cash(db, tx.account_id, tx.currency, -tx.amount, source)
        if tx.fee:
            await _adjust_cash(db, tx.account_id, tx.fee_currency, tx.fee, source)
    elif tx.transaction_type in (TransactionType.TRANSFER_IN, TransactionType.TRANSFER_OUT):
        if tx.instrument_id:
            await _adjust_holding(db, tx.account_id, tx.instrument_id, -tx.quantity, source)
    elif tx.transaction_type == TransactionType.FX_EXCHANGE:
        if tx.instrument_id:
            await _adjust_holding(db, tx.account_id, tx.instrument_id, -tx.quantity, source)
        if tx.fee:
            await _adjust_cash(db, tx.account_id, tx.fee_currency, tx.fee, source)
    elif tx.transaction_type in (TransactionType.DEPOSIT, TransactionType.WITHDRAW):
        if tx.instrument_id:
            await _adjust_holding(db, tx.account_id, tx.instrument_id, -tx.quantity, source)
    elif tx.transaction_type in (TransactionType.DIVIDEND, TransactionType.INTEREST, TransactionType.FEE):
        await _adjust_cash(db, tx.account_id, tx.currency, -tx.amount, source)
    elif tx.transaction_type == TransactionType.MANUAL_ADJUSTMENT and tx.instrument_id:
        await _adjust_holding(db, tx.account_id, tx.instrument_id, -tx.quantity, source)


async def _linked_group(db: AsyncSession, tx: Transaction) -> list[Transaction]:
    rows = [tx]
    if tx.linked_transaction_id:
        linked = await db.get(Transaction, tx.linked_transaction_id)
        if linked is not None:
            rows.append(linked)
    return rows


async def update_transaction_metadata(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    data: TransactionMetadataUpdate,
    *,
    commit: bool = True,
) -> list[Transaction]:
    tx = await db.get(Transaction, transaction_id)
    if tx is None:
        raise ValueError("transaction_not_found")
    rows = await _linked_group(db, tx)
    values = data.model_dump(exclude_unset=True)
    try:
        for row in rows:
            for field, value in values.items():
                setattr(row, field, value)
        await _finish_write(db, commit)
        return rows
    except Exception:
        if commit:
            await db.rollback()
        raise


async def delete_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    *,
    commit: bool = True,
) -> list[uuid.UUID]:
    tx = await db.get(Transaction, transaction_id)
    if tx is None:
        raise ValueError("transaction_not_found")
    if tx.is_reversed or (tx.external_ref or "").startswith("reversal:"):
        raise ValueError("reversal_transaction_cannot_be_deleted")
    rows = await _linked_group(db, tx)
    ids = [row.id for row in rows]
    try:
        for row in rows:
            await _apply_inverse(db, row)
        for row in rows:
            await db.delete(row)
        await _finish_write(db, commit)
        return ids
    except Exception:
        if commit:
            await db.rollback()
        raise


async def reverse_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    *,
    commit: bool = True,
) -> list[Transaction]:
    tx = await db.get(Transaction, transaction_id)
    if tx is None:
        raise ValueError("transaction_not_found")
    rows = await _linked_group(db, tx)
    if any(row.is_reversed for row in rows):
        raise ValueError("transaction_already_reversed")

    reversals: list[Transaction] = []
    reversal_ids = [uuid.uuid4() for _ in rows]
    for index, row in enumerate(rows):
        linked_id = reversal_ids[1 - index] if len(rows) == 2 else None
        reversal = _transaction(
            id=reversal_ids[index],
            account_id=row.account_id,
            instrument_id=row.instrument_id,
            transaction_type=row.transaction_type,
            quantity=-row.quantity,
            price=row.price,
            currency=row.currency,
            amount=-row.amount,
            fee=-row.fee,
            fee_currency=row.fee_currency,
            trade_date=date.today(),
            executed_at=None,
            settlement_date=None,
            external_ref=f"reversal:{row.id}",
            linked_transaction_id=linked_id,
            note=f"Reversal of {row.id}" + (f" · {row.note}" if row.note else ""),
            source=row.source,
        )
        reversals.append(reversal)

    try:
        for row in rows:
            await _apply_inverse(db, row)
        for row, reversal in zip(rows, reversals, strict=True):
            row.is_reversed = True
            row.reversed_by_id = reversal.id
        db.add_all(reversals)
        await _finish_write(db, commit)
        return reversals
    except Exception:
        if commit:
            await db.rollback()
        raise


def _filtered_statement(
    account_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_id: uuid.UUID | None = None,
):
    stmt = select(Transaction)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    if date_from:
        stmt = stmt.where(Transaction.trade_date >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.trade_date <= date_to)
    if instrument_id:
        stmt = stmt.where(Transaction.instrument_id == instrument_id)
    return stmt


async def list_transactions(
    db: AsyncSession,
    offset: int = 0,
    limit: int = 100,
    account_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_id: uuid.UUID | None = None,
) -> tuple[list[Transaction], int, dict[str, Decimal]]:
    filtered = _filtered_statement(account_id, transaction_type, date_from, date_to, instrument_id)
    count_stmt = select(func.count()).select_from(filtered.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    all_rows = list((await db.execute(filtered)).scalars().all())
    total_buy = sum((-row.amount for row in all_rows if row.transaction_type == TransactionType.BUY), ZERO)
    total_sell = sum((row.amount for row in all_rows if row.transaction_type == TransactionType.SELL), ZERO)
    net_cash_flow = sum((row.amount - row.fee for row in all_rows), ZERO)

    page_stmt = (
        filtered.options(selectinload(Transaction.account), selectinload(Transaction.instrument))
        .order_by(Transaction.trade_date.desc(), Transaction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list((await db.execute(page_stmt)).scalars().all())
    return items, total, {
        "total_buy": total_buy,
        "total_sell": total_sell,
        "net_cash_flow": net_cash_flow,
    }


async def get_transaction(db: AsyncSession, transaction_id: uuid.UUID) -> Transaction | None:
    stmt = (
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .options(selectinload(Transaction.account), selectinload(Transaction.instrument))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def recalculate_holdings_from_ledger(
    db: AsyncSession,
    account_id: uuid.UUID | None = None,
    *,
    commit: bool = True,
) -> int:
    holdings_stmt = select(Holding)
    transactions_stmt = select(Transaction).order_by(Transaction.created_at, Transaction.id)
    if account_id:
        await _require_account(db, account_id)
        holdings_stmt = holdings_stmt.where(Holding.account_id == account_id)
        transactions_stmt = transactions_stmt.where(Transaction.account_id == account_id)
    holdings = list((await db.execute(holdings_stmt)).scalars().all())
    for holding in holdings:
        holding.quantity = ZERO

    transactions = list((await db.execute(transactions_stmt)).scalars().all())
    try:
        for tx in transactions:
            source = tx.source if isinstance(tx.source, TransactionSource) else TransactionSource(str(tx.source))
            if tx.transaction_type in (TransactionType.BUY, TransactionType.SELL):
                if tx.instrument_id:
                    await _adjust_holding(db, tx.account_id, tx.instrument_id, tx.quantity, source)
                await _adjust_cash(db, tx.account_id, tx.currency, tx.amount, source)
                if tx.fee:
                    await _adjust_cash(db, tx.account_id, tx.fee_currency, -tx.fee, source)
            elif tx.transaction_type in (TransactionType.TRANSFER_IN, TransactionType.TRANSFER_OUT):
                if tx.instrument_id:
                    await _adjust_holding(db, tx.account_id, tx.instrument_id, tx.quantity, source)
            elif tx.transaction_type == TransactionType.FX_EXCHANGE:
                if tx.instrument_id:
                    await _adjust_holding(db, tx.account_id, tx.instrument_id, tx.quantity, source)
                if tx.fee:
                    await _adjust_cash(db, tx.account_id, tx.fee_currency, -tx.fee, source)
            elif tx.transaction_type in (TransactionType.DEPOSIT, TransactionType.WITHDRAW):
                if tx.instrument_id:
                    await _adjust_holding(db, tx.account_id, tx.instrument_id, tx.quantity, source)
            elif tx.transaction_type in (TransactionType.DIVIDEND, TransactionType.INTEREST, TransactionType.FEE):
                await _adjust_cash(db, tx.account_id, tx.currency, tx.amount, source)
            elif tx.transaction_type == TransactionType.MANUAL_ADJUSTMENT and tx.instrument_id:
                await _adjust_holding(db, tx.account_id, tx.instrument_id, tx.quantity, source)
        await _finish_write(db, commit)
        return len(transactions)
    except Exception:
        if commit:
            await db.rollback()
        raise
