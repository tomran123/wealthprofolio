import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.family_scope import (
    family_scoped_get,
    get_bound_request_context,
    require_bound_family_id,
)
from app.models import (
    Account,
    Holding,
    Instrument,
    Transaction,
    TransactionMetadataProjection,
)
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
from app.services.event_ledger_service import record_transaction_event

ZERO = Decimal("0")
CENT = Decimal("0.01")
ProjectionWriter = Callable[[], Awaitable[None]]
IDEMPOTENCY_FINGERPRINT_FIELD = "idempotency_fingerprint"


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _holding_source(source: TransactionSource) -> HoldingSource:
    return HoldingSource(source.value)


def _transaction_source(source: TransactionSource | HoldingSource | str) -> TransactionSource:
    value = source.value if hasattr(source, "value") else str(source)
    return TransactionSource(value)


def _command_fingerprint(command: str, payload: Any) -> str:
    """Return a stable fingerprint for one idempotent business command."""

    encoded = json.dumps(
        {"command": command, "payload": payload},
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _finish_write(db: AsyncSession, commit: bool) -> None:
    if commit:
        await db.commit()
    else:
        await db.flush()


async def _require_account(db: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await family_scoped_get(db, Account, account_id)
    if account is None:
        raise ValueError("account_not_found")
    return account


async def _require_instrument(db: AsyncSession, instrument_id: uuid.UUID) -> Instrument:
    instrument = await family_scoped_get(db, Instrument, instrument_id)
    if instrument is None:
        raise ValueError("instrument_not_found")
    return instrument


async def _cash_instrument(db: AsyncSession, currency: str) -> Instrument:
    code = currency.upper()
    family_id = require_bound_family_id(db)
    # A cash instrument is a family-local singleton. The transaction-scoped
    # advisory lock prevents concurrent first-use requests from creating two
    # rows before either is visible to the other.
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"{family_id}:cash:{code}", 0)
            )
        )
    )
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


async def _locked_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
) -> Holding | None:
    stmt = (
        select(Holding)
        .where(
            Holding.account_id == account_id,
            Holding.instrument_id == instrument_id,
        )
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _adjust_holding(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    delta: Decimal,
    source: TransactionSource,
    event_id: uuid.UUID,
) -> Holding:
    holding = await _locked_holding(db, account_id, instrument_id)
    if holding is None:
        holding = Holding(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=delta,
            source=_holding_source(source),
            projection_version=1,
            last_event_id=event_id,
        )
        db.add(holding)
    else:
        holding.quantity += delta
        holding.source = _holding_source(source)
        holding.projection_version += 1
        holding.last_event_id = event_id
    await db.flush()
    return holding


async def _adjust_cash(
    db: AsyncSession,
    account_id: uuid.UUID,
    currency: str,
    delta: Decimal,
    source: TransactionSource,
    event_id: uuid.UUID,
) -> Holding:
    cash = await _cash_instrument(db, currency)
    return await _adjust_holding(db, account_id, cash.id, delta, source, event_id)


async def _ensure_cash_available(
    db: AsyncSession,
    account_id: uuid.UUID,
    currency: str,
    required: Decimal,
) -> None:
    if required <= 0:
        return
    code = currency.upper()
    cash = (
        await db.execute(
            select(Instrument)
            .where(
                Instrument.asset_class == AssetClass.CASH,
                Instrument.currency == code,
                Instrument.symbol == code,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if cash is None:
        raise ValueError("insufficient_cash")
    holding = await _locked_holding(db, account_id, cash.id)
    available = holding.quantity if holding is not None else ZERO
    if available < required:
        raise ValueError("insufficient_cash")


def _new_transaction(
    db: AsyncSession,
    *,
    idempotency_key: str | None = None,
    idempotency_fingerprint: str | None = None,
    correlation_id: uuid.UUID | None = None,
    causation_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Transaction:
    family_id = require_bound_family_id(db)
    context = get_bound_request_context(db)
    transaction_id = kwargs.pop("id", uuid.uuid4())
    currency = str(kwargs.pop("currency")).upper()
    fee_currency = str(kwargs.pop("fee_currency", None) or currency).upper()
    metadata_json = dict(metadata or {})
    if idempotency_key is not None:
        if idempotency_fingerprint is None:
            raise ValueError("idempotency_fingerprint_required")
        metadata_json[IDEMPOTENCY_FINGERPRINT_FIELD] = idempotency_fingerprint
    return Transaction(
        id=transaction_id,
        family_id=family_id,
        event_version=1,
        idempotency_key=idempotency_key or f"transaction:{transaction_id}",
        correlation_id=correlation_id or transaction_id,
        causation_id=causation_id,
        created_by_user_id=context.user_id if context is not None else None,
        metadata_json=metadata_json,
        currency=currency,
        fee_currency=fee_currency,
        **kwargs,
    )


async def _existing_transaction(
    db: AsyncSession,
    idempotency_key: str | None,
    fingerprint: str,
) -> Transaction | None:
    if not idempotency_key:
        return None
    family_id = require_bound_family_id(db)
    # Serialize contenders before checking the unique key. This closes the
    # check-then-insert race while preserving a single database transaction.
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(
                    f"{family_id}:transaction-idempotency:{idempotency_key}",
                    0,
                )
            )
        )
    )
    existing = (
        await db.execute(
            select(Transaction).where(Transaction.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    stored_fingerprint = (existing.metadata_json or {}).get(
        IDEMPOTENCY_FINGERPRINT_FIELD
    )
    if stored_fingerprint != fingerprint:
        raise ValueError("idempotency_key_reused_with_different_payload")
    return existing


async def _persist_events(
    db: AsyncSession,
    transactions: list[Transaction],
    apply_projection: ProjectionWriter,
    *,
    commit: bool,
) -> None:
    db.add_all(transactions)
    db.add_all(
        [
            TransactionMetadataProjection(
                family_id=transaction.family_id,
                transaction_id=transaction.id,
                trade_date=transaction.trade_date,
                executed_at=transaction.executed_at,
                settlement_date=transaction.settlement_date,
                external_ref=transaction.external_ref,
                note=transaction.note,
                version=1,
                last_event_id=transaction.id,
            )
            for transaction in transactions
        ]
    )
    await db.flush()
    await apply_projection()
    for transaction in transactions:
        await record_transaction_event(db, transaction)
    await _finish_write(db, commit)


async def create_buy_transaction(
    db: AsyncSession,
    data: BuyTransactionCreate,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    fingerprint = _command_fingerprint("buy", data.model_dump(mode="json"))
    existing = await _existing_transaction(db, idempotency_key, fingerprint)
    if existing is not None:
        return existing
    await _require_account(db, data.account_id)
    await _require_instrument(db, data.instrument_id)
    gross = _money(data.quantity * data.price)
    fee_currency = (data.fee_currency or data.currency).upper()
    requirements: dict[str, Decimal] = {data.currency.upper(): gross}
    requirements[fee_currency] = requirements.get(fee_currency, ZERO) + data.fee
    for currency, required in requirements.items():
        await _ensure_cash_available(db, data.account_id, currency, required)
    tx = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
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

    async def project() -> None:
        await _apply_transaction_projection(db, tx)

    try:
        await _persist_events(db, [tx], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    fingerprint = _command_fingerprint("sell", data.model_dump(mode="json"))
    existing = await _existing_transaction(db, idempotency_key, fingerprint)
    if existing is not None:
        return existing
    await _require_account(db, data.account_id)
    await _require_instrument(db, data.instrument_id)
    holding = await _locked_holding(db, data.account_id, data.instrument_id)
    if holding is None or holding.quantity < data.quantity:
        raise ValueError("insufficient_holding")
    fee_currency = (data.fee_currency or data.currency).upper()
    gross = _money(data.quantity * data.price)
    if data.fee:
        required_cash = (
            data.fee
            if fee_currency != data.currency.upper()
            else max(data.fee - gross, ZERO)
        )
        await _ensure_cash_available(
            db,
            data.account_id,
            fee_currency,
            required_cash,
        )
    tx = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
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

    async def project() -> None:
        await _apply_transaction_projection(db, tx)

    try:
        await _persist_events(db, [tx], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> tuple[Transaction, Transaction]:
    fingerprint = _command_fingerprint("transfer", data.model_dump(mode="json"))
    out_key = f"{idempotency_key}:out" if idempotency_key else None
    in_key = f"{idempotency_key}:in" if idempotency_key else None
    existing_out = await _existing_transaction(db, out_key, fingerprint)
    existing_in = await _existing_transaction(db, in_key, fingerprint)
    if existing_out is not None and existing_in is not None:
        return existing_out, existing_in
    if existing_out is not None or existing_in is not None:
        raise ValueError("partial_idempotent_transaction_group")
    await _require_account(db, data.from_account_id)
    await _require_account(db, data.to_account_id)
    await _require_instrument(db, data.instrument_id)
    holding = await _locked_holding(db, data.from_account_id, data.instrument_id)
    if holding is None or holding.quantity < data.quantity:
        raise ValueError("insufficient_holding")

    out_id, in_id = uuid.uuid4(), uuid.uuid4()
    group_correlation = correlation_id or uuid.uuid4()
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
    outgoing = _new_transaction(
        db,
        id=out_id,
        idempotency_key=out_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=group_correlation,
        account_id=data.from_account_id,
        transaction_type=TransactionType.TRANSFER_OUT,
        quantity=-data.quantity,
        linked_transaction_id=in_id,
        **common,
    )
    incoming = _new_transaction(
        db,
        id=in_id,
        idempotency_key=in_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=group_correlation,
        causation_id=out_id,
        account_id=data.to_account_id,
        transaction_type=TransactionType.TRANSFER_IN,
        quantity=data.quantity,
        linked_transaction_id=out_id,
        **common,
    )

    async def project() -> None:
        await _apply_transaction_projection(db, outgoing)
        await _apply_transaction_projection(db, incoming)

    try:
        await _persist_events(db, [outgoing, incoming], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> tuple[Transaction, Transaction]:
    fingerprint = _command_fingerprint(
        "currency_exchange",
        data.model_dump(mode="json"),
    )
    out_key = f"{idempotency_key}:out" if idempotency_key else None
    in_key = f"{idempotency_key}:in" if idempotency_key else None
    existing_out = await _existing_transaction(db, out_key, fingerprint)
    existing_in = await _existing_transaction(db, in_key, fingerprint)
    if existing_out is not None and existing_in is not None:
        return existing_out, existing_in
    if existing_out is not None or existing_in is not None:
        raise ValueError("partial_idempotent_transaction_group")
    await _require_account(db, data.account_id)
    from_currency, to_currency = data.from_currency.upper(), data.to_currency.upper()
    fee_currency = (data.fee_currency or from_currency).upper()
    requirements = {from_currency: data.from_amount}
    requirements[fee_currency] = requirements.get(fee_currency, ZERO) + data.fee
    for currency, required in requirements.items():
        await _ensure_cash_available(db, data.account_id, currency, required)
    from_cash = await _cash_instrument(db, from_currency)
    to_cash = await _cash_instrument(db, to_currency)
    out_id, in_id = uuid.uuid4(), uuid.uuid4()
    group_correlation = correlation_id or uuid.uuid4()
    rate = data.rate or data.to_amount / data.from_amount
    outgoing = _new_transaction(
        db,
        id=out_id,
        idempotency_key=out_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=group_correlation,
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
    incoming = _new_transaction(
        db,
        id=in_id,
        idempotency_key=in_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=group_correlation,
        causation_id=out_id,
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

    async def project() -> None:
        await _apply_transaction_projection(db, outgoing)
        await _apply_transaction_projection(db, incoming)

    try:
        await _persist_events(db, [outgoing, incoming], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    fingerprint = _command_fingerprint("income", data.model_dump(mode="json"))
    existing = await _existing_transaction(db, idempotency_key, fingerprint)
    if existing is not None:
        return existing
    await _require_account(db, data.account_id)
    if data.instrument_id:
        await _require_instrument(db, data.instrument_id)
    amount = _money(data.amount)
    tx = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
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

    async def project() -> None:
        await _apply_transaction_projection(db, tx)

    try:
        await _persist_events(db, [tx], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    fingerprint = _command_fingerprint("fee", data.model_dump(mode="json"))
    existing = await _existing_transaction(db, idempotency_key, fingerprint)
    if existing is not None:
        return existing
    await _require_account(db, data.account_id)
    if data.instrument_id:
        await _require_instrument(db, data.instrument_id)
    amount = _money(data.amount)
    await _ensure_cash_available(db, data.account_id, data.currency, amount)
    tx = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
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

    async def project() -> None:
        await _apply_transaction_projection(db, tx)

    try:
        await _persist_events(db, [tx], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    fingerprint = _command_fingerprint("cash", data.model_dump(mode="json"))
    existing = await _existing_transaction(db, idempotency_key, fingerprint)
    if existing is not None:
        return existing
    await _require_account(db, data.account_id)
    cash = await _cash_instrument(db, data.currency)
    signed = data.amount if data.transaction_type == TransactionType.DEPOSIT else -data.amount
    if signed < 0:
        await _ensure_cash_available(db, data.account_id, data.currency, abs(signed))
    tx = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
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

    async def project() -> None:
        await _apply_transaction_projection(db, tx)

    try:
        await _persist_events(db, [tx], project, commit=commit)
        return tx
    except Exception:
        if commit:
            await db.rollback()
        raise


async def _create_position_event(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    delta_quantity: Decimal,
    currency: str,
    transaction_type: TransactionType,
    source: TransactionSource,
    trade_date: date,
    note: str | None,
    executed_at=None,
    commit: bool = True,
    idempotency_key: str | None = None,
    idempotency_fingerprint: str,
    correlation_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Transaction:
    existing = await _existing_transaction(
        db,
        idempotency_key,
        idempotency_fingerprint,
    )
    if existing is not None:
        return existing
    await _require_account(db, account_id)
    instrument = await _require_instrument(db, instrument_id)
    if instrument.asset_class != AssetClass.LIABILITY:
        holding = await _locked_holding(db, account_id, instrument_id)
        current_quantity = holding.quantity if holding is not None else ZERO
        if current_quantity + delta_quantity < ZERO:
            raise ValueError("insufficient_holding")
    tx = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=idempotency_fingerprint,
        correlation_id=correlation_id,
        metadata=metadata,
        account_id=account_id,
        instrument_id=instrument_id,
        transaction_type=transaction_type,
        quantity=delta_quantity,
        price=None,
        currency=currency,
        amount=ZERO,
        fee=ZERO,
        fee_currency=currency,
        trade_date=trade_date,
        executed_at=executed_at,
        note=note,
        source=source,
    )

    async def project() -> None:
        await _apply_transaction_projection(db, tx)

    try:
        await _persist_events(db, [tx], project, commit=commit)
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
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    fingerprint = _command_fingerprint(
        "manual_adjustment",
        data.model_dump(mode="json"),
    )
    return await _create_position_event(
        db,
        account_id=data.account_id,
        instrument_id=data.instrument_id,
        delta_quantity=data.delta_quantity,
        currency=data.currency,
        transaction_type=TransactionType.MANUAL_ADJUSTMENT,
        source=data.source,
        trade_date=data.trade_date,
        executed_at=data.executed_at,
        note=data.note,
        commit=commit,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
    )


async def create_opening_balance(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    quantity: Decimal,
    currency: str,
    source: TransactionSource | HoldingSource = TransactionSource.MANUAL,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    note: str | None = None,
    idempotency_fingerprint_override: str | None = None,
) -> Transaction:
    fingerprint = idempotency_fingerprint_override or _command_fingerprint(
        "opening_balance",
        {
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": quantity,
            "currency": currency.upper(),
            "source": _transaction_source(source).value,
            "metadata": metadata or {},
            "note": note,
        },
    )
    return await _create_position_event(
        db,
        account_id=account_id,
        instrument_id=instrument_id,
        delta_quantity=quantity,
        currency=currency,
        transaction_type=TransactionType.OPENING_BALANCE,
        source=_transaction_source(source),
        trade_date=date.today(),
        note=note,
        commit=commit,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
        metadata=metadata,
    )


async def create_reconciliation_transaction(
    db: AsyncSession,
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
    currency: str,
    source: TransactionSource | HoldingSource = TransactionSource.MANUAL,
    *,
    target_quantity: Decimal | None = None,
    delta_quantity: Decimal | None = None,
    commit: bool = True,
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    note: str | None = None,
    idempotency_fingerprint_override: str | None = None,
) -> Transaction:
    if (target_quantity is None) == (delta_quantity is None):
        raise ValueError("reconciliation_requires_target_or_delta")
    fingerprint = idempotency_fingerprint_override or _command_fingerprint(
        "reconciliation",
        {
            "account_id": account_id,
            "instrument_id": instrument_id,
            "currency": currency.upper(),
            "source": _transaction_source(source).value,
            "target_quantity": target_quantity,
            "delta_quantity": delta_quantity,
            "metadata": metadata or {},
            "note": note,
        },
    )
    await _require_account(db, account_id)
    instrument = await _require_instrument(db, instrument_id)
    if target_quantity is not None:
        holding = await _locked_holding(db, account_id, instrument_id)
        current = holding.quantity if holding is not None else ZERO
        delta_quantity = target_quantity - current
        metadata = {
            **(metadata or {}),
            "target_quantity": str(target_quantity),
            "previous_quantity": str(current),
        }
    assert delta_quantity is not None
    return await _create_position_event(
        db,
        account_id=account_id,
        instrument_id=instrument_id,
        delta_quantity=delta_quantity,
        currency=currency or instrument.currency,
        transaction_type=TransactionType.RECONCILIATION,
        source=_transaction_source(source),
        trade_date=date.today(),
        note=note,
        commit=commit,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=correlation_id,
        metadata=metadata,
    )


async def _apply_transaction_projection(db: AsyncSession, tx: Transaction) -> None:
    source = _transaction_source(tx.source)
    if tx.transaction_type in (TransactionType.BUY, TransactionType.SELL):
        if tx.instrument_id:
            await _adjust_holding(
                db, tx.account_id, tx.instrument_id, tx.quantity, source, tx.id
            )
        await _adjust_cash(db, tx.account_id, tx.currency, tx.amount, source, tx.id)
        if tx.fee:
            await _adjust_cash(
                db, tx.account_id, tx.fee_currency, -tx.fee, source, tx.id
            )
    elif tx.transaction_type in (
        TransactionType.TRANSFER_IN,
        TransactionType.TRANSFER_OUT,
        TransactionType.DEPOSIT,
        TransactionType.WITHDRAW,
        TransactionType.FX_EXCHANGE,
        TransactionType.MANUAL_ADJUSTMENT,
        TransactionType.OPENING_BALANCE,
        TransactionType.RECONCILIATION,
        TransactionType.SPLIT,
        TransactionType.REVERSE_SPLIT,
        TransactionType.MERGER,
        TransactionType.STOCK_DIVIDEND,
    ):
        if tx.instrument_id:
            await _adjust_holding(
                db, tx.account_id, tx.instrument_id, tx.quantity, source, tx.id
            )
        if tx.transaction_type == TransactionType.FX_EXCHANGE and tx.fee:
            await _adjust_cash(
                db, tx.account_id, tx.fee_currency, -tx.fee, source, tx.id
            )
    elif tx.transaction_type in (
        TransactionType.DIVIDEND,
        TransactionType.INTEREST,
        TransactionType.FEE,
        TransactionType.TAX,
    ):
        await _adjust_cash(db, tx.account_id, tx.currency, tx.amount, source, tx.id)


async def _locked_linked_group(
    db: AsyncSession,
    transaction_id: uuid.UUID,
) -> list[Transaction]:
    candidate = await family_scoped_get(db, Transaction, transaction_id)
    if candidate is None:
        raise ValueError("transaction_not_found")
    ids = [candidate.id]
    if candidate.linked_transaction_id is not None:
        ids.append(candidate.linked_transaction_id)
    locked = list(
        (
            await db.execute(
                select(Transaction)
                .where(Transaction.id.in_(ids))
                .order_by(Transaction.id)
                .with_for_update()
            )
        ).scalars()
    )
    by_id = {row.id: row for row in locked}
    if transaction_id not in by_id:
        raise ValueError("transaction_not_found")
    rows = [by_id[transaction_id]]
    linked_id = by_id[transaction_id].linked_transaction_id
    if linked_id is not None:
        linked = by_id.get(linked_id)
        if linked is None:
            raise ValueError("linked_transaction_not_found")
        rows.append(linked)
    return rows


async def _ensure_reversal_projection_is_nonnegative(
    db: AsyncSession,
    reversals: list[Transaction],
) -> None:
    deltas: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}

    async def add_delta(
        account_id: uuid.UUID,
        instrument_id: uuid.UUID,
        delta: Decimal,
    ) -> None:
        key = (account_id, instrument_id)
        deltas[key] = deltas.get(key, ZERO) + delta

    for tx in reversals:
        if tx.transaction_type in (TransactionType.BUY, TransactionType.SELL):
            if tx.instrument_id is not None:
                await add_delta(tx.account_id, tx.instrument_id, tx.quantity)
            cash = await _cash_instrument(db, tx.currency)
            await add_delta(tx.account_id, cash.id, tx.amount)
            if tx.fee:
                fee_cash = await _cash_instrument(db, tx.fee_currency)
                await add_delta(tx.account_id, fee_cash.id, -tx.fee)
        elif tx.transaction_type in (
            TransactionType.TRANSFER_IN,
            TransactionType.TRANSFER_OUT,
            TransactionType.DEPOSIT,
            TransactionType.WITHDRAW,
            TransactionType.FX_EXCHANGE,
            TransactionType.MANUAL_ADJUSTMENT,
            TransactionType.OPENING_BALANCE,
            TransactionType.RECONCILIATION,
            TransactionType.SPLIT,
            TransactionType.REVERSE_SPLIT,
            TransactionType.MERGER,
            TransactionType.STOCK_DIVIDEND,
        ):
            if tx.instrument_id is not None:
                await add_delta(tx.account_id, tx.instrument_id, tx.quantity)
            if tx.transaction_type == TransactionType.FX_EXCHANGE and tx.fee:
                fee_cash = await _cash_instrument(db, tx.fee_currency)
                await add_delta(tx.account_id, fee_cash.id, -tx.fee)
        elif tx.transaction_type in (
            TransactionType.DIVIDEND,
            TransactionType.INTEREST,
            TransactionType.FEE,
            TransactionType.TAX,
        ):
            cash = await _cash_instrument(db, tx.currency)
            await add_delta(tx.account_id, cash.id, tx.amount)

    for (account_id, instrument_id), delta in deltas.items():
        if delta >= ZERO:
            continue
        instrument = await _require_instrument(db, instrument_id)
        if instrument.asset_class == AssetClass.LIABILITY:
            continue
        holding = await _locked_holding(db, account_id, instrument_id)
        current = holding.quantity if holding is not None else ZERO
        if current + delta < ZERO:
            if instrument.asset_class == AssetClass.CASH:
                raise ValueError("reversal_would_create_negative_cash")
            raise ValueError("reversal_would_create_negative_holding")


async def update_transaction_metadata(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    data: TransactionMetadataUpdate,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
) -> list[Transaction]:
    serialized_values = data.model_dump(exclude_unset=True, mode="json")
    fingerprint = _command_fingerprint(
        "update_transaction_metadata",
        {
            "transaction_id": transaction_id,
            "changes": serialized_values,
        },
    )
    existing = await _existing_transaction(db, idempotency_key, fingerprint)
    if existing is not None:
        return [existing]
    tx = await family_scoped_get(db, Transaction, transaction_id)
    if tx is None:
        raise ValueError("transaction_not_found")
    values = data.model_dump(exclude_unset=True)
    projection = (
        await db.execute(
            select(TransactionMetadataProjection)
            .where(TransactionMetadataProjection.transaction_id == tx.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if projection is None:
        raise ValueError("transaction_metadata_projection_not_found")

    def serialized(value: Any) -> Any:
        return value.isoformat() if isinstance(value, (date, datetime)) else value

    previous_values = {
        field: serialized(getattr(projection, field))
        for field in values
    }
    event = _new_transaction(
        db,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        correlation_id=tx.correlation_id,
        causation_id=tx.id,
        metadata={
            "amends_transaction_id": str(tx.id),
            "changes": serialized_values,
            "previous": previous_values,
        },
        account_id=tx.account_id,
        instrument_id=tx.instrument_id,
        transaction_type=TransactionType.METADATA_AMENDED,
        quantity=ZERO,
        price=None,
        currency=tx.currency,
        amount=ZERO,
        fee=ZERO,
        fee_currency=tx.currency,
        trade_date=date.today(),
        executed_at=None,
        settlement_date=None,
        external_ref=None,
        note="Metadata amendment",
        source=tx.source,
    )

    async def project() -> None:
        for field, value in values.items():
            setattr(projection, field, value)
        projection.version += 1
        projection.last_event_id = event.id

    try:
        await _persist_events(db, [event], project, commit=commit)
        return [event]
    except Exception:
        if commit:
            await db.rollback()
        raise


async def delete_draft_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    *,
    commit: bool = True,
) -> None:
    tx = await family_scoped_get(db, Transaction, transaction_id)
    if tx is None:
        raise ValueError("transaction_not_found")
    if (tx.metadata_json or {}).get("status") != "draft":
        raise ValueError("posted_transaction_requires_reversal")
    family_id = require_bound_family_id(db)
    await db.execute(
        select(
            func.wp_delete_draft_transaction(
                family_id,
                transaction_id,
            )
        )
    )
    db.expunge(tx)
    await _finish_write(db, commit)


async def delete_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
) -> list[uuid.UUID]:
    """Compatibility command used by the Agent: deletion means compensation."""

    rows = await reverse_transaction(
        db,
        transaction_id,
        commit=commit,
        idempotency_key=idempotency_key,
    )
    return [row.id for row in rows]


async def reverse_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    *,
    commit: bool = True,
    idempotency_key: str | None = None,
) -> list[Transaction]:
    fingerprint = _command_fingerprint(
        "reverse_transaction",
        {"transaction_id": transaction_id},
    )
    if idempotency_key is not None:
        existing_first = await _existing_transaction(
            db,
            f"{idempotency_key}:0",
            fingerprint,
        )
        existing_second = await _existing_transaction(
            db,
            f"{idempotency_key}:1",
            fingerprint,
        )
        if existing_first is not None:
            if existing_first.linked_transaction_id is None:
                if existing_second is not None:
                    raise ValueError("partial_idempotent_transaction_group")
                return [existing_first]
            if (
                existing_second is None
                or existing_first.linked_transaction_id != existing_second.id
                or existing_second.linked_transaction_id != existing_first.id
                or existing_first.correlation_id != existing_second.correlation_id
            ):
                raise ValueError("partial_idempotent_transaction_group")
            return [existing_first, existing_second]
        if existing_second is not None:
            raise ValueError("partial_idempotent_transaction_group")

    rows = await _locked_linked_group(db, transaction_id)
    if any(row.is_reversed or row.reversal_of_id is not None for row in rows):
        raise ValueError("transaction_already_reversed")

    reversal_ids = [uuid.uuid4() for _ in rows]
    group_correlation = uuid.uuid4()

    if any(row.transaction_type == TransactionType.METADATA_AMENDED for row in rows):
        if len(rows) != 1:
            raise ValueError("metadata_amendment_cannot_be_linked")
        original = rows[0]
        metadata = original.metadata_json or {}
        previous_values = metadata.get("previous")
        target_value = metadata.get("amends_transaction_id")
        if not isinstance(previous_values, dict) or not target_value:
            raise ValueError("metadata_amendment_not_reversible")
        try:
            target_id = uuid.UUID(str(target_value))
            restore = TransactionMetadataUpdate.model_validate(previous_values)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata_amendment_not_reversible") from exc
        projection = (
            await db.execute(
                select(TransactionMetadataProjection)
                .where(TransactionMetadataProjection.transaction_id == target_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if projection is None:
            raise ValueError("transaction_metadata_projection_not_found")
        if projection.last_event_id != original.id:
            raise ValueError("transaction_metadata_changed_after_amendment")

        restore_values = restore.model_dump(exclude_unset=True)

        def serialized(value: Any) -> Any:
            return value.isoformat() if isinstance(value, (date, datetime)) else value

        current_values = {
            field: serialized(getattr(projection, field))
            for field in restore_values
        }
        reversal = _new_transaction(
            db,
            id=reversal_ids[0],
            idempotency_key=(
                f"{idempotency_key}:0"
                if idempotency_key
                else f"reversal:{original.id}:{reversal_ids[0]}"
            ),
            idempotency_fingerprint=fingerprint,
            correlation_id=group_correlation,
            causation_id=original.id,
            metadata={
                "reversal_reason": "explicit_user_request",
                "amends_transaction_id": str(target_id),
                "changes": previous_values,
                "previous": current_values,
                "compensates_metadata_event_id": str(original.id),
            },
            account_id=original.account_id,
            instrument_id=original.instrument_id,
            transaction_type=TransactionType.METADATA_AMENDED,
            quantity=ZERO,
            price=None,
            currency=original.currency,
            amount=ZERO,
            fee=ZERO,
            fee_currency=original.fee_currency,
            trade_date=date.today(),
            executed_at=None,
            settlement_date=None,
            external_ref=f"reversal:{original.id}",
            note=f"Metadata reversal of {original.id}",
            source=original.source,
            reversal_of_id=original.id,
        )

        async def project_metadata_reversal() -> None:
            for field, value in restore_values.items():
                setattr(projection, field, value)
            projection.version += 1
            projection.last_event_id = reversal.id
            await db.execute(
                select(
                    func.wp_mark_transaction_reversed(
                        original.family_id,
                        original.id,
                        reversal.id,
                    )
                )
            )
            await db.refresh(
                original,
                attribute_names=["is_reversed", "reversed_by_id", "updated_at"],
            )

        try:
            await _persist_events(
                db,
                [reversal],
                project_metadata_reversal,
                commit=commit,
            )
            return [reversal]
        except Exception:
            if commit:
                await db.rollback()
            raise

    reversals: list[Transaction] = []
    for index, row in enumerate(rows):
        key = (
            f"{idempotency_key}:{index}"
            if idempotency_key
            else f"reversal:{row.id}:{reversal_ids[index]}"
        )
        linked_id = reversal_ids[1 - index] if len(rows) == 2 else None
        reversals.append(
            _new_transaction(
                db,
                id=reversal_ids[index],
                idempotency_key=key,
                idempotency_fingerprint=fingerprint,
                correlation_id=group_correlation,
                causation_id=row.id,
                metadata={"reversal_reason": "explicit_user_request"},
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
                reversal_of_id=row.id,
            )
        )

    async def project() -> None:
        for original, reversal in zip(rows, reversals, strict=True):
            await _apply_transaction_projection(db, reversal)
            await db.execute(
                select(
                    func.wp_mark_transaction_reversed(
                        original.family_id,
                        original.id,
                        reversal.id,
                    )
                )
            )
            await db.refresh(
                original,
                attribute_names=["is_reversed", "reversed_by_id", "updated_at"],
            )

    try:
        await _ensure_reversal_projection_is_nonnegative(db, reversals)
        await _persist_events(db, reversals, project, commit=commit)
        return reversals
    except Exception:
        if commit:
            await db.rollback()
        raise


def _filter_conditions(
    account_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_id: uuid.UUID | None = None,
) -> list:
    conditions = []
    if account_id:
        conditions.append(Transaction.account_id == account_id)
    if transaction_type:
        conditions.append(Transaction.transaction_type == transaction_type)
    if date_from:
        conditions.append(TransactionMetadataProjection.trade_date >= date_from)
    if date_to:
        conditions.append(TransactionMetadataProjection.trade_date <= date_to)
    if instrument_id:
        conditions.append(Transaction.instrument_id == instrument_id)
    return conditions


def _filtered_statement(
    account_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_id: uuid.UUID | None = None,
):
    return (
        select(Transaction)
        .join(
            TransactionMetadataProjection,
            TransactionMetadataProjection.transaction_id == Transaction.id,
        )
        .where(
            *_filter_conditions(
                account_id,
                transaction_type,
                date_from,
                date_to,
                instrument_id,
            )
        )
    )


async def list_transactions(
    db: AsyncSession,
    offset: int = 0,
    limit: int = 100,
    account_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_id: uuid.UUID | None = None,
) -> tuple[list[Transaction], int, dict[str, list[dict[str, Decimal | str]]]]:
    conditions = _filter_conditions(
        account_id, transaction_type, date_from, date_to, instrument_id
    )
    filtered = _filtered_statement(
        account_id, transaction_type, date_from, date_to, instrument_id
    )
    count_stmt = (
        select(func.count(Transaction.id))
        .join(
            TransactionMetadataProjection,
            TransactionMetadataProjection.transaction_id == Transaction.id,
        )
        .where(*conditions)
    )
    total = int((await db.execute(count_stmt)).scalar_one())

    # Keep nominal currencies separate. Summing USD and EUR into one number is
    # financially meaningless, and fees may be charged in a third currency.
    amount_summary_stmt = (
        select(
            Transaction.currency,
            func.coalesce(
                func.sum(
                    case(
                        (
                            Transaction.transaction_type == TransactionType.BUY,
                            -Transaction.amount,
                        ),
                        else_=ZERO,
                    )
                ),
                ZERO,
            ).label("total_buy"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Transaction.transaction_type == TransactionType.SELL,
                            Transaction.amount,
                        ),
                        else_=ZERO,
                    )
                ),
                ZERO,
            ).label("total_sell"),
            func.coalesce(func.sum(Transaction.amount), ZERO).label("amount_flow"),
        )
        .join(
            TransactionMetadataProjection,
            TransactionMetadataProjection.transaction_id == Transaction.id,
        )
        .where(*conditions)
        .group_by(Transaction.currency)
    )
    fee_summary_stmt = (
        select(
            Transaction.fee_currency,
            func.coalesce(func.sum(Transaction.fee), ZERO).label("fees"),
        )
        .join(
            TransactionMetadataProjection,
            TransactionMetadataProjection.transaction_id == Transaction.id,
        )
        .where(*conditions, Transaction.fee != ZERO)
        .group_by(Transaction.fee_currency)
    )
    summaries: dict[str, dict[str, Decimal]] = {}
    for currency, total_buy, total_sell, amount_flow in (
        await db.execute(amount_summary_stmt)
    ).all():
        code = str(currency).upper()
        summaries[code] = {
            "total_buy": Decimal(total_buy),
            "total_sell": Decimal(total_sell),
            "net_cash_flow": Decimal(amount_flow),
        }
    for currency, fees in (await db.execute(fee_summary_stmt)).all():
        code = str(currency).upper()
        summary = summaries.setdefault(
            code,
            {
                "total_buy": ZERO,
                "total_sell": ZERO,
                "net_cash_flow": ZERO,
            },
        )
        summary["net_cash_flow"] -= Decimal(fees)

    page_stmt = (
        filtered.options(
            selectinload(Transaction.account),
            selectinload(Transaction.instrument),
            selectinload(Transaction.metadata_projection),
        )
        .order_by(
            TransactionMetadataProjection.trade_date.desc(),
            Transaction.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    items = list((await db.execute(page_stmt)).scalars().all())
    return items, total, {
        "by_currency": [
            {"currency": currency, **summary}
            for currency, summary in sorted(summaries.items())
        ]
    }


async def get_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
) -> Transaction | None:
    family_id = require_bound_family_id(db)
    stmt = (
        select(Transaction)
        .where(
            Transaction.id == transaction_id,
            Transaction.family_id == family_id,
        )
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.instrument),
            selectinload(Transaction.metadata_projection),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def recalculate_holdings_from_ledger(
    db: AsyncSession,
    account_id: uuid.UUID | None = None,
    *,
    commit: bool = True,
) -> int:
    holdings_stmt = select(Holding)
    transactions_stmt = select(Transaction).order_by(
        Transaction.created_at, Transaction.id
    )
    if account_id:
        await _require_account(db, account_id)
        holdings_stmt = holdings_stmt.where(Holding.account_id == account_id)
        transactions_stmt = transactions_stmt.where(Transaction.account_id == account_id)
    holdings = list((await db.execute(holdings_stmt)).scalars().all())
    for holding in holdings:
        holding.quantity = ZERO
        holding.projection_version = 0
        holding.last_event_id = None

    transactions = list((await db.execute(transactions_stmt)).scalars().all())
    try:
        for tx in transactions:
            await _apply_transaction_projection(db, tx)
        await _finish_write(db, commit)
        return len(transactions)
    except Exception:
        if commit:
            await db.rollback()
        raise
