import io
import uuid
from decimal import Decimal, InvalidOperation

import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import family_scoped_get
from app.models import Account, Holding, ImportBatch, Institution, Instrument, Owner
from app.models.enums import AssetClass, ImportBatchStatus, PriceSourceType, TransactionSource
from app.services import transaction_service, valuation_service

TEMPLATE_COLUMNS = [
    "Owner",
    "Institution",
    "Account",
    "Instrument Name",
    "Ticker",
    "Asset Type",
    "Quantity",
    "Currency",
    "Cost Price",
    "Current Price",
    "Valuation Date",
    "Exposure Group",
    "Country",
    "Liquidity Type",
]

ASSET_TYPE_MAP = {
    "cash": AssetClass.CASH,
    "equity": AssetClass.EQUITY,
    "stock": AssetClass.EQUITY,
    "etf": AssetClass.ETF,
    "bond": AssetClass.BOND,
    "fund": AssetClass.FUND,
    "real_estate": AssetClass.REAL_ESTATE,
    "real estate": AssetClass.REAL_ESTATE,
    "private_equity": AssetClass.PRIVATE_EQUITY,
    "private equity": AssetClass.PRIVATE_EQUITY,
    "company_equity": AssetClass.COMPANY_EQUITY,
    "gold": AssetClass.GOLD,
    "crypto": AssetClass.CRYPTO,
    "liability": AssetClass.LIABILITY,
    "custom": AssetClass.CUSTOM,
}

MARKET_PRICED_CLASSES = {AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUND, AssetClass.CRYPTO, AssetClass.GOLD}

FUZZY_MATCH_THRESHOLD = 88


def generate_template_csv() -> str:
    return ",".join(TEMPLATE_COLUMNS) + "\n"


def _read_table(filename: str, content: bytes) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(content), dtype=str).fillna("")
    return pd.read_excel(io.BytesIO(content), dtype=str).fillna("")


def _best_fuzzy_match(name: str, candidates: dict[str, uuid.UUID]) -> uuid.UUID | None:
    if not name:
        return None
    best_score = 0.0
    best_id: uuid.UUID | None = None
    for candidate_name, candidate_id in candidates.items():
        score = fuzz.token_sort_ratio(name.lower(), candidate_name.lower())
        if score > best_score:
            best_score = score
            best_id = candidate_id
    if best_score >= FUZZY_MATCH_THRESHOLD:
        return best_id
    return None


async def parse_and_preview(db: AsyncSession, filename: str, content: bytes) -> ImportBatch:
    df = _read_table(filename, content)
    missing_columns = [c for c in TEMPLATE_COLUMNS if c not in df.columns]

    owners = {o.name: o.id for o in (await db.execute(select(Owner))).scalars().all()}
    institutions = {i.name: i.id for i in (await db.execute(select(Institution))).scalars().all()}
    accounts = {a.name: a.id for a in (await db.execute(select(Account))).scalars().all()}
    instruments = {(i.symbol or i.name): i.id for i in (await db.execute(select(Instrument))).scalars().all()}

    parsed_rows: list[dict] = []
    error_count = 0
    matched_count = 0
    created_count = 0

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        row_errors: list[str] = []

        owner_name = str(row_dict.get("Owner", "")).strip()
        institution_name = str(row_dict.get("Institution", "")).strip()
        account_name = str(row_dict.get("Account", "")).strip()
        instrument_name = str(row_dict.get("Instrument Name", "")).strip()
        ticker = str(row_dict.get("Ticker", "")).strip()
        quantity_raw = str(row_dict.get("Quantity", "")).strip()

        if not account_name:
            row_errors.append("missing_account")
        if not instrument_name:
            row_errors.append("missing_instrument_name")

        quantity: str | None = None
        if quantity_raw:
            try:
                quantity = str(Decimal(quantity_raw))
            except InvalidOperation:
                row_errors.append("invalid_quantity")

        owner_match = _best_fuzzy_match(owner_name, owners) if owner_name else None
        institution_match = _best_fuzzy_match(institution_name, institutions) if institution_name else None
        account_match = _best_fuzzy_match(account_name, accounts) if account_name else None
        instrument_match = _best_fuzzy_match(ticker or instrument_name, instruments)

        if instrument_match:
            matched_count += 1
        else:
            created_count += 1
        if row_errors:
            error_count += 1

        parsed_rows.append(
            {
                "row_index": int(idx),
                "owner_name": owner_name,
                "owner_id": str(owner_match) if owner_match else None,
                "institution_name": institution_name,
                "institution_id": str(institution_match) if institution_match else None,
                "account_name": account_name,
                "account_id": str(account_match) if account_match else None,
                "instrument_name": instrument_name,
                "ticker": ticker or None,
                "instrument_id": str(instrument_match) if instrument_match else None,
                "asset_type": str(row_dict.get("Asset Type", "")).strip().lower(),
                "quantity": quantity,
                "currency": str(row_dict.get("Currency", "")).strip().upper() or None,
                "cost_price": str(row_dict.get("Cost Price", "")).strip() or None,
                "current_price": str(row_dict.get("Current Price", "")).strip() or None,
                "valuation_date": str(row_dict.get("Valuation Date", "")).strip() or None,
                "exposure_group": str(row_dict.get("Exposure Group", "")).strip() or None,
                "country": str(row_dict.get("Country", "")).strip().upper() or None,
                "liquidity_type": str(row_dict.get("Liquidity Type", "")).strip() or None,
                "errors": row_errors,
            }
        )

    batch = ImportBatch(
        filename=filename,
        status=ImportBatchStatus.PENDING,
        row_count=len(parsed_rows),
        matched_count=matched_count,
        created_count=created_count,
        error_count=error_count,
        parsed_rows={"rows": parsed_rows, "missing_columns": missing_columns},
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def get_batch(db: AsyncSession, batch_id: uuid.UUID) -> ImportBatch | None:
    return await family_scoped_get(db, ImportBatch, batch_id)


async def _get_or_create_owner(db: AsyncSession, cache: dict[str, uuid.UUID], name: str) -> uuid.UUID:
    if name in cache:
        return cache[name]
    owner = Owner(name=name)
    db.add(owner)
    await db.flush()
    cache[name] = owner.id
    return owner.id


async def _get_or_create_institution(db: AsyncSession, cache: dict[str, uuid.UUID], name: str) -> uuid.UUID:
    if name in cache:
        return cache[name]
    institution = Institution(name=name)
    db.add(institution)
    await db.flush()
    cache[name] = institution.id
    return institution.id


async def _get_or_create_account(
    db: AsyncSession,
    cache: dict[tuple[str, uuid.UUID, uuid.UUID], uuid.UUID],
    name: str,
    institution_id: uuid.UUID,
    owner_id: uuid.UUID,
    currency: str,
) -> uuid.UUID:
    key = (name.casefold(), institution_id, owner_id)
    if key in cache:
        return cache[key]
    account = Account(name=name, institution_id=institution_id, owner_id=owner_id, base_currency=currency or "USD")
    db.add(account)
    await db.flush()
    cache[key] = account.id
    return account.id


async def _get_or_create_instrument(
    db: AsyncSession,
    cache: dict[str, uuid.UUID],
    key: str,
    name: str,
    symbol: str | None,
    asset_type: str,
    currency: str,
) -> uuid.UUID:
    if key in cache:
        return cache[key]
    asset_class = ASSET_TYPE_MAP.get(asset_type, AssetClass.CUSTOM)
    price_source = PriceSourceType.MANUAL
    if asset_class in MARKET_PRICED_CLASSES:
        price_source = PriceSourceType.MARKET
    elif asset_class == AssetClass.CASH:
        price_source = PriceSourceType.FX_DERIVED
    instrument = Instrument(
        name=name, symbol=symbol, asset_class=asset_class, currency=currency or "USD", price_source_type=price_source
    )
    db.add(instrument)
    await db.flush()
    cache[key] = instrument.id
    return instrument.id


async def commit_batch(db: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    batch = (
        await db.execute(
            select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise ValueError("batch_not_found")
    if batch.status == ImportBatchStatus.COMMITTED:
        return batch

    rows: list[dict] = batch.parsed_rows.get("rows", [])
    owner_cache: dict[str, uuid.UUID] = {}
    institution_cache: dict[str, uuid.UUID] = {}
    account_cache: dict[tuple[str, uuid.UUID, uuid.UUID], uuid.UUID] = {}
    instrument_cache: dict[str, uuid.UUID] = {}

    try:
        for row in rows:
            if row.get("errors"):
                continue

            owner_id = (
                uuid.UUID(row["owner_id"])
                if row.get("owner_id")
                else await _get_or_create_owner(
                    db, owner_cache, row["owner_name"] or "Unassigned"
                )
            )
            institution_id = (
                uuid.UUID(row["institution_id"])
                if row.get("institution_id")
                else await _get_or_create_institution(
                    db,
                    institution_cache,
                    row["institution_name"] or "Unknown",
                )
            )
            account_id = (
                uuid.UUID(row["account_id"])
                if row.get("account_id")
                else await _get_or_create_account(
                    db,
                    account_cache,
                    row["account_name"],
                    institution_id,
                    owner_id,
                    row.get("currency") or "USD",
                )
            )
            instrument_key = row.get("ticker") or row["instrument_name"]
            instrument_id = (
                uuid.UUID(row["instrument_id"])
                if row.get("instrument_id")
                else await _get_or_create_instrument(
                    db,
                    instrument_cache,
                    instrument_key,
                    row["instrument_name"],
                    row.get("ticker"),
                    row.get("asset_type", ""),
                    row.get("currency") or "USD",
                )
            )

            quantity = Decimal(row["quantity"]) if row.get("quantity") else Decimal("0")
            existing_holding = (
                await db.execute(
                    select(Holding).where(
                        Holding.account_id == account_id,
                        Holding.instrument_id == instrument_id,
                    )
                )
            ).scalar_one_or_none()
            event_key = f"import:{batch.id}:row:{row['row_index']}"
            event_metadata = {
                "import_batch_id": str(batch.id),
                "row_index": row["row_index"],
            }
            if existing_holding is None:
                await transaction_service.create_opening_balance(
                    db,
                    account_id,
                    instrument_id,
                    quantity,
                    row.get("currency") or "USD",
                    TransactionSource.IMPORT,
                    commit=False,
                    idempotency_key=event_key,
                    metadata=event_metadata,
                )
            else:
                await transaction_service.create_reconciliation_transaction(
                    db,
                    account_id,
                    instrument_id,
                    row.get("currency") or "USD",
                    TransactionSource.IMPORT,
                    target_quantity=quantity,
                    commit=False,
                    idempotency_key=event_key,
                    metadata=event_metadata,
                )

            current_price = row.get("current_price")
            if current_price:
                try:
                    price_value = Decimal(current_price)
                    await valuation_service.set_manual_valuation(
                        db,
                        instrument_id,
                        price_value,
                        row.get("currency") or "USD",
                        note="csv_import",
                        commit=False,
                    )
                except InvalidOperation:
                    pass

        batch.status = ImportBatchStatus.COMMITTED
        await db.commit()
        await db.refresh(batch)
        return batch
    except Exception:
        await db.rollback()
        raise
