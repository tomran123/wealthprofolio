import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.family_scope import get_bound_request_context, require_bound_family_id
from app.models import (
    AuditEvent,
    JournalEntry,
    JournalPosting,
    OutboxEvent,
    Transaction,
)
from app.models.enums import TransactionType

ZERO = Decimal("0")


def _posting(
    *,
    entry_id: uuid.UUID,
    family_id: uuid.UUID,
    account_code: str,
    currency: str,
    account_id: uuid.UUID | None,
    instrument_id: uuid.UUID | None,
    debit: Decimal = ZERO,
    credit: Decimal = ZERO,
    quantity: Decimal | None = None,
) -> JournalPosting:
    return JournalPosting(
        family_id=family_id,
        journal_entry_id=entry_id,
        account_code=account_code,
        account_id=account_id,
        instrument_id=instrument_id,
        currency=currency.upper(),
        debit=abs(debit),
        credit=abs(credit),
        quantity=quantity,
        metadata_json={},
    )


def _standard_postings(
    tx: Transaction,
    entry_id: uuid.UUID,
    family_id: uuid.UUID,
) -> list[JournalPosting]:
    currency = tx.currency.upper()
    amount = abs(tx.amount)
    asset_code = (
        f"asset:instrument:{tx.instrument_id}"
        if tx.instrument_id
        else f"asset:account:{tx.account_id}"
    )
    cash_code = f"asset:cash:{tx.account_id}:{currency}"
    contra_code = f"equity:event:{tx.transaction_type.value}"
    debit_code, credit_code = asset_code, contra_code

    if tx.transaction_type == TransactionType.BUY:
        debit_code, credit_code = asset_code, cash_code
    elif tx.transaction_type == TransactionType.SELL:
        debit_code, credit_code = cash_code, asset_code
    elif tx.transaction_type in (TransactionType.DIVIDEND, TransactionType.INTEREST):
        debit_code, credit_code = cash_code, f"income:{tx.transaction_type.value}"
    elif tx.transaction_type in (
        TransactionType.FEE,
        TransactionType.TAX,
        TransactionType.WITHDRAW,
    ):
        debit_code, credit_code = f"expense:{tx.transaction_type.value}", cash_code
    elif tx.transaction_type == TransactionType.DEPOSIT:
        debit_code, credit_code = cash_code, "equity:contribution"
    elif tx.transaction_type == TransactionType.FX_EXCHANGE:
        if tx.amount >= 0:
            debit_code, credit_code = cash_code, "asset:fx_clearing"
        else:
            debit_code, credit_code = "asset:fx_clearing", cash_code
    elif tx.amount < 0:
        debit_code, credit_code = contra_code, asset_code

    postings = [
        _posting(
            entry_id=entry_id,
            family_id=family_id,
            account_code=debit_code,
            account_id=tx.account_id,
            instrument_id=tx.instrument_id,
            currency=currency,
            debit=amount,
            quantity=tx.quantity,
        ),
        _posting(
            entry_id=entry_id,
            family_id=family_id,
            account_code=credit_code,
            account_id=tx.account_id,
            instrument_id=tx.instrument_id,
            currency=currency,
            credit=amount,
            quantity=-tx.quantity,
        ),
    ]
    if tx.fee:
        fee_amount = abs(tx.fee)
        fee_currency = tx.fee_currency.upper()
        postings.extend(
            [
                _posting(
                    entry_id=entry_id,
                    family_id=family_id,
                    account_code="expense:fee",
                    account_id=tx.account_id,
                    instrument_id=tx.instrument_id,
                    currency=fee_currency,
                    debit=fee_amount,
                ),
                _posting(
                    entry_id=entry_id,
                    family_id=family_id,
                    account_code=f"asset:cash:{tx.account_id}:{fee_currency}",
                    account_id=tx.account_id,
                    instrument_id=None,
                    currency=fee_currency,
                    credit=fee_amount,
                ),
            ]
        )
    return postings


async def _reversal_postings(
    db: AsyncSession,
    tx: Transaction,
    entry_id: uuid.UUID,
    family_id: uuid.UUID,
) -> list[JournalPosting]:
    original_entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.transaction_id == tx.reversal_of_id)
            .options(selectinload(JournalEntry.postings))
        )
    ).scalar_one_or_none()
    if original_entry is None:
        return _standard_postings(tx, entry_id, family_id)
    return [
        _posting(
            entry_id=entry_id,
            family_id=family_id,
            account_code=posting.account_code,
            account_id=posting.account_id,
            instrument_id=posting.instrument_id,
            currency=posting.currency,
            debit=posting.credit,
            credit=posting.debit,
            quantity=-posting.quantity if posting.quantity is not None else None,
        )
        for posting in original_entry.postings
    ]


async def record_transaction_event(db: AsyncSession, tx: Transaction) -> JournalEntry:
    """Append journal, audit and outbox rows for one persisted transaction.

    The caller owns the surrounding transaction. No commit happens here.
    """

    family_id = require_bound_family_id(db)
    if tx.family_id != family_id:
        raise ValueError("cross_family_transaction_forbidden")
    context = get_bound_request_context(db)
    actor_user_id = context.user_id if context is not None else tx.created_by_user_id
    entry = JournalEntry(
        family_id=family_id,
        transaction_id=tx.id,
        event_type=(
            "transaction.reversed"
            if tx.reversal_of_id is not None
            else f"transaction.{tx.transaction_type.value}"
        ),
        event_version=tx.event_version,
        correlation_id=tx.correlation_id,
        description=f"{tx.transaction_type.value} transaction",
        created_by_user_id=actor_user_id,
        metadata_json={"source": tx.source.value, **(tx.metadata_json or {})},
    )
    db.add(entry)
    await db.flush()
    postings = (
        await _reversal_postings(db, tx, entry.id, family_id)
        if tx.reversal_of_id is not None
        else _standard_postings(tx, entry.id, family_id)
    )
    db.add_all(postings)

    event_type = (
        "transaction.reversed"
        if tx.reversal_of_id is not None
        else f"transaction.{tx.transaction_type.value}"
    )
    db.add(
        AuditEvent(
            family_id=family_id,
            actor_user_id=actor_user_id,
            action=event_type,
            aggregate_type="transaction",
            aggregate_id=tx.id,
            correlation_id=tx.correlation_id,
            causation_id=tx.causation_id,
            summary_json={
                "account_id": str(tx.account_id),
                "instrument_id": str(tx.instrument_id) if tx.instrument_id else None,
                "transaction_type": tx.transaction_type.value,
                "currency": tx.currency,
                "event_version": tx.event_version,
            },
        )
    )
    db.add(
        OutboxEvent(
            family_id=family_id,
            aggregate_type="transaction",
            aggregate_id=tx.id,
            event_type=event_type,
            event_version=tx.event_version,
            idempotency_key=tx.idempotency_key,
            correlation_id=tx.correlation_id,
            causation_id=tx.causation_id,
            payload_json={
                "transaction_id": str(tx.id),
                "family_id": str(family_id),
                "account_id": str(tx.account_id),
                "instrument_id": str(tx.instrument_id) if tx.instrument_id else None,
                "transaction_type": tx.transaction_type.value,
                "quantity": str(tx.quantity),
                "amount": str(tx.amount),
                "currency": tx.currency,
                "reversal_of_id": str(tx.reversal_of_id) if tx.reversal_of_id else None,
            },
        )
    )
    await db.flush()
    return entry


async def assert_journal_entries_balanced(
    db: AsyncSession,
    transaction_ids: list[uuid.UUID] | None = None,
) -> None:
    statement = select(JournalEntry).options(selectinload(JournalEntry.postings))
    if transaction_ids:
        statement = statement.where(JournalEntry.transaction_id.in_(transaction_ids))
    entries = list((await db.execute(statement)).scalars().all())
    for entry in entries:
        totals: dict[str, tuple[Decimal, Decimal]] = {}
        for posting in entry.postings:
            debit, credit = totals.get(posting.currency, (ZERO, ZERO))
            totals[posting.currency] = (debit + posting.debit, credit + posting.credit)
        if len(entry.postings) < 2 or any(debit != credit for debit, credit in totals.values()):
            raise ValueError(f"journal_entry_unbalanced:{entry.id}")
