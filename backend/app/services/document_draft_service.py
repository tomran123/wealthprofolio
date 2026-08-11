import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import family_scoped_get
from app.models import Account, Instrument
from app.models.document import (
    Document,
    DocumentExtraction,
    DocumentLink,
    DocumentVersion,
)
from app.models.enums import TransactionSource, TransactionType
from app.schemas.document import DocumentTransactionDraft, DocumentTransactionDraftItem
from app.schemas.transaction import (
    BuyTransactionCreate,
    CashTransactionCreate,
    FeeTransactionCreate,
    IncomeTransactionCreate,
    SellTransactionCreate,
)
from app.services import transaction_service

SUPPORTED_DRAFT_TYPES = {
    "buy",
    "sell",
    "deposit",
    "withdraw",
    "dividend",
    "interest",
    "fee",
    "opening_balance",
    "reconciliation",
}


def _decimal(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return format(Decimal(str(value).replace(",", "")), "f")
    except InvalidOperation:
        return None


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


async def _match_account(
    db: AsyncSession,
    document: Document,
    name: str | None,
) -> Account | None:
    if document.account_id:
        return await family_scoped_get(db, Account, document.account_id)
    if not name:
        return None
    rows = list(
        (
            await db.execute(
                select(Account)
                .where(Account.name.ilike(str(name).strip()))
                .limit(2)
            )
        ).scalars()
    )
    return rows[0] if len(rows) == 1 else None


async def _match_instrument(
    db: AsyncSession,
    symbol: str | None,
    name: str | None,
) -> Instrument | None:
    conditions = []
    if symbol:
        conditions.append(Instrument.symbol.ilike(str(symbol).strip()))
    if name:
        conditions.append(Instrument.name.ilike(str(name).strip()))
    if not conditions:
        return None
    rows = list(
        (
            await db.execute(
                select(Instrument)
                .where(or_(*conditions))
                .limit(3)
            )
        ).scalars()
    )
    if len(rows) == 1:
        return rows[0]
    if symbol:
        exact = [
            item for item in rows if (item.symbol or "").casefold() == str(symbol).casefold()
        ]
        if len(exact) == 1:
            return exact[0]
    return None


async def latest_transaction_draft(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> DocumentExtraction | None:
    return (
        await db.execute(
            select(DocumentExtraction)
            .where(
                DocumentExtraction.document_id == document_id,
                DocumentExtraction.extraction_type == "transaction_draft",
            )
            .order_by(DocumentExtraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_transaction_draft(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    commit: bool = True,
) -> DocumentExtraction:
    # Serialize draft creation per document so an API request and an Agent
    # confirmation cannot create two simultaneously-reviewable drafts.
    document = (
        await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise ValueError("document_not_found")
    if document.status != "ready":
        raise ValueError("document_not_ready")

    version = (
        await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version_number == document.current_version_number,
            )
        )
    ).scalar_one()
    source = (
        await db.execute(
            select(DocumentExtraction)
            .where(
                DocumentExtraction.document_id == document.id,
                DocumentExtraction.document_version_id == version.id,
                DocumentExtraction.extraction_type == "financial_document",
                DocumentExtraction.status == "ready",
            )
            .order_by(DocumentExtraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if source is None:
        raise ValueError("document_extraction_not_found")
    latest = await latest_transaction_draft(db, document_id)
    if latest is not None and latest.status == "pending_review":
        return latest
    if (
        latest is not None
        and latest.status == "confirmed"
        and str((latest.data_json or {}).get("source_extraction_id") or "")
        == str(source.id)
    ):
        return latest

    items: list[dict[str, Any]] = []
    warnings = list((source.data_json or {}).get("warnings") or [])
    raw_items = (source.data_json or {}).get("items") or []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        transaction_type = str(raw.get("transaction_type") or "").lower().strip()
        if not transaction_type and document.document_type == "holding_snapshot" and raw.get("quantity"):
            transaction_type = "reconciliation"
        if transaction_type == "transfer":
            warnings.append(f"Item {index + 1}: transfer direction and destination need review.")
            continue
        if transaction_type not in SUPPORTED_DRAFT_TYPES:
            warnings.append(f"Item {index + 1}: unsupported or missing transaction type.")
            continue
        account = await _match_account(db, document, raw.get("account"))
        instrument = await _match_instrument(
            db,
            raw.get("symbol"),
            raw.get("instrument"),
        )
        if account is None:
            warnings.append(f"Item {index + 1}: account could not be matched.")
        if transaction_type in ("buy", "sell", "opening_balance", "reconciliation") and instrument is None:
            warnings.append(f"Item {index + 1}: instrument could not be matched.")
        currency = str(
            raw.get("currency")
            or (instrument.currency if instrument else None)
            or (account.base_currency if account else None)
            or "USD"
        ).upper()
        confidence = raw.get("confidence")
        try:
            parsed_confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            parsed_confidence = None
        items.append(
            {
                "id": f"item-{index + 1}",
                "transaction_type": transaction_type,
                "account_id": str(account.id) if account else None,
                "account_name": account.name if account else raw.get("account"),
                "instrument_id": str(instrument.id) if instrument else None,
                "instrument_name": instrument.name if instrument else raw.get("instrument"),
                "instrument_symbol": instrument.symbol if instrument else raw.get("symbol"),
                "quantity": _decimal(raw.get("quantity")),
                "price": _decimal(raw.get("price")),
                "amount": _decimal(raw.get("amount")),
                "currency": currency,
                "fee": _decimal(raw.get("fee")),
                "trade_date": _date(raw.get("date")),
                "note": str(raw.get("note") or "")[:500] or None,
                "confidence": parsed_confidence,
                "page_number": raw.get("page_number"),
                "citation": raw.get("citation"),
            }
        )
    if not items:
        warnings.append("No postable transaction candidates were extracted.")
    draft = DocumentExtraction(
        family_id=document.family_id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_type="transaction_draft",
        schema_version=1,
        status="pending_review",
        summary=f"{len(items)} transaction candidates awaiting explicit confirmation",
        confidence=(
            sum(item["confidence"] for item in items if item["confidence"] is not None)
            / len([item for item in items if item["confidence"] is not None])
            if any(item["confidence"] is not None for item in items)
            else None
        ),
        provider="document_draft",
        data_json={
            "source_extraction_id": str(source.id),
            "items": items,
            "warnings": list(dict.fromkeys(warnings)),
        },
        citations_json=[
            {
                "page_number": item["page_number"],
                "citation": item["citation"],
            }
            for item in items
            if item["page_number"]
        ],
    )
    db.add(draft)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return draft


def draft_schema(draft: DocumentExtraction) -> DocumentTransactionDraft:
    items = []
    for item in (draft.data_json or {}).get("items", []):
        try:
            items.append(DocumentTransactionDraftItem.model_validate(item))
        except ValidationError:
            continue
    return DocumentTransactionDraft(
        id=draft.id,
        document_id=draft.document_id,
        extraction_id=draft.id,
        status=draft.status,
        items=items,
        warnings=list((draft.data_json or {}).get("warnings") or []),
        created_at=draft.created_at,
        resolved_at=draft.resolved_at,
    )


def _required(item: dict[str, Any], index: int, *fields: str) -> None:
    missing = [field for field in fields if item.get(field) in (None, "")]
    if missing:
        raise ValueError(f"draft_item_{index + 1}_missing_{'_'.join(missing)}")


async def _post_item(
    db: AsyncSession,
    document: Document,
    draft: DocumentExtraction,
    item: dict[str, Any],
    index: int,
) -> list:
    transaction_type = str(item.get("transaction_type") or "")
    key = f"document:{document.id}:extraction:{draft.id}:draft:{index}"
    _required(item, index, "account_id", "currency")
    account_id = uuid.UUID(str(item["account_id"]))
    trade_date = (
        date.fromisoformat(item["trade_date"])
        if item.get("trade_date")
        else document.document_date or datetime.now(timezone.utc).date()
    )
    currency = str(item["currency"]).upper()
    source = TransactionSource.AGENT
    note = item.get("note") or f"Confirmed document draft {draft.id}, item {index + 1}"

    if transaction_type in ("buy", "sell"):
        _required(item, index, "instrument_id", "quantity", "price")
        model = BuyTransactionCreate if transaction_type == "buy" else SellTransactionCreate
        payload = model(
            account_id=account_id,
            instrument_id=uuid.UUID(str(item["instrument_id"])),
            quantity=Decimal(str(item["quantity"])),
            price=Decimal(str(item["price"])),
            currency=currency,
            fee=Decimal(str(item.get("fee") or "0")),
            fee_currency=currency,
            trade_date=trade_date,
            note=note,
            source=source,
        )
        transaction = (
            await transaction_service.create_buy_transaction(
                db, payload, commit=False, idempotency_key=key
            )
            if transaction_type == "buy"
            else await transaction_service.create_sell_transaction(
                db, payload, commit=False, idempotency_key=key
            )
        )
        return [transaction]
    if transaction_type in ("deposit", "withdraw"):
        _required(item, index, "amount")
        transaction = await transaction_service.create_cash_transaction(
            db,
            CashTransactionCreate(
                account_id=account_id,
                amount=abs(Decimal(str(item["amount"]))),
                currency=currency,
                transaction_type=TransactionType(transaction_type),
                trade_date=trade_date,
                note=note,
                source=source,
            ),
            commit=False,
            idempotency_key=key,
        )
        return [transaction]
    if transaction_type in ("dividend", "interest"):
        _required(item, index, "amount")
        transaction = await transaction_service.create_income_transaction(
            db,
            IncomeTransactionCreate(
                account_id=account_id,
                instrument_id=(
                    uuid.UUID(str(item["instrument_id"])) if item.get("instrument_id") else None
                ),
                amount=abs(Decimal(str(item["amount"]))),
                currency=currency,
                transaction_type=TransactionType(transaction_type),
                trade_date=trade_date,
                note=note,
                source=source,
            ),
            commit=False,
            idempotency_key=key,
        )
        return [transaction]
    if transaction_type == "fee":
        _required(item, index, "amount")
        transaction = await transaction_service.create_fee_transaction(
            db,
            FeeTransactionCreate(
                account_id=account_id,
                instrument_id=(
                    uuid.UUID(str(item["instrument_id"])) if item.get("instrument_id") else None
                ),
                amount=abs(Decimal(str(item["amount"]))),
                currency=currency,
                trade_date=trade_date,
                note=note,
                source=source,
            ),
            commit=False,
            idempotency_key=key,
        )
        return [transaction]
    if transaction_type == "opening_balance":
        _required(item, index, "instrument_id", "quantity")
        transaction = await transaction_service.create_opening_balance(
            db,
            account_id=account_id,
            instrument_id=uuid.UUID(str(item["instrument_id"])),
            quantity=Decimal(str(item["quantity"])),
            currency=currency,
            source=source,
            commit=False,
            idempotency_key=key,
            metadata={
                "document_id": str(document.id),
                "document_extraction_id": str(draft.id),
                "source_page": item.get("page_number"),
            },
            note=note,
        )
        return [transaction]
    if transaction_type == "reconciliation":
        _required(item, index, "instrument_id", "quantity")
        transaction = await transaction_service.create_reconciliation_transaction(
            db,
            account_id=account_id,
            instrument_id=uuid.UUID(str(item["instrument_id"])),
            currency=currency,
            source=source,
            target_quantity=Decimal(str(item["quantity"])),
            commit=False,
            idempotency_key=key,
            metadata={
                "document_id": str(document.id),
                "document_extraction_id": str(draft.id),
                "source_page": item.get("page_number"),
            },
            note=note,
        )
        return [transaction]
    raise ValueError(f"draft_item_{index + 1}_unsupported_transaction_type")


async def confirm_transaction_draft(
    db: AsyncSession,
    document_id: uuid.UUID,
    draft_id: uuid.UUID,
) -> DocumentExtraction:
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise ValueError("document_not_found")
    draft = (
        await db.execute(
            select(DocumentExtraction)
            .where(
                DocumentExtraction.id == draft_id,
                DocumentExtraction.document_id == document.id,
                DocumentExtraction.extraction_type == "transaction_draft",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None:
        raise ValueError("transaction_draft_not_found")
    if draft.status == "confirmed":
        return draft
    if draft.status != "pending_review":
        raise ValueError("transaction_draft_not_pending")
    items = list((draft.data_json or {}).get("items") or [])
    if not items:
        raise ValueError("transaction_draft_has_no_items")

    transaction_ids: list[str] = []
    try:
        for index, item in enumerate(items):
            transactions = await _post_item(db, document, draft, item, index)
            for transaction in transactions:
                transaction_ids.append(str(transaction.id))
                db.add(
                    DocumentLink(
                        family_id=document.family_id,
                        document_id=document.id,
                        extraction_id=draft.id,
                        target_type="transaction",
                        target_id=transaction.id,
                        relation="source_document",
                        metadata_json={"draft_item_index": index},
                    )
                )
        draft.status = "confirmed"
        draft.resolved_at = datetime.now(timezone.utc)
        draft.data_json = {
            **(draft.data_json or {}),
            "transaction_ids": transaction_ids,
        }
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return draft


async def cancel_transaction_draft(
    db: AsyncSession,
    document_id: uuid.UUID,
    draft_id: uuid.UUID,
) -> DocumentExtraction:
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise ValueError("document_not_found")
    draft = (
        await db.execute(
            select(DocumentExtraction)
            .where(
                DocumentExtraction.id == draft_id,
                DocumentExtraction.document_id == document.id,
                DocumentExtraction.extraction_type == "transaction_draft",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None:
        raise ValueError("transaction_draft_not_found")
    if draft.status == "cancelled":
        return draft
    if draft.status != "pending_review":
        raise ValueError("transaction_draft_not_pending")
    draft.status = "cancelled"
    draft.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return draft
