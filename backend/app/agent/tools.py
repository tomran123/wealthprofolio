import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.state import json_value
from app.core.config import get_settings
from app.core.family_scope import family_scoped_get
from app.models import Account, ExposureGroup, Holding, Institution, Owner
from app.models.enums import HoldingSource, TransactionSource, TransactionType
from app.schemas.account import AccountCreate, AccountUpdate
from app.schemas.document import KnowledgeFilters
from app.schemas.exposure_group import ExposureGroupCreate, ExposureGroupUpdate
from app.schemas.institution import InstitutionCreate, InstitutionUpdate
from app.schemas.instrument import InstrumentCreate, InstrumentUpdate
from app.schemas.owner import OwnerCreate, OwnerUpdate
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
from app.services import (
    account_service,
    document_draft_service,
    exposure_group_service,
    holding_service,
    institution_service,
    instrument_service,
    knowledge_service,
    market_instrument_service,
    market_price_history_service,
    owner_service,
    price_refresh_service,
    settings_service,
    transaction_service,
    valuation_service,
    valuation_snapshot_service,
)

settings = get_settings()

ToolEffect = Literal["read", "create", "update", "delete"]
TOOL_EFFECTS: dict[str, ToolEffect] = {}
TOOL_RESOURCES: dict[str, str] = {}


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    *,
    effect: ToolEffect = "read",
    resource: str,
) -> dict[str, Any]:
    TOOL_EFFECTS[name] = effect
    TOOL_RESOURCES[name] = resource
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


ID = {"type": "string", "format": "uuid"}
NUMBER = {"type": "number"}
DATE = {"type": "string", "format": "date"}
DATETIME = {"type": "string", "format": "date-time"}
CURRENCY = {"type": "string", "minLength": 3, "maxLength": 3}
ACCOUNT_TYPE = {"type": "string", "enum": ["cash", "brokerage", "mixed"]}
ASSET_CLASS = {
    "type": "string",
    "enum": [
        "cash",
        "equity",
        "etf",
        "bond",
        "fund",
        "real_estate",
        "private_equity",
        "company_equity",
        "gold",
        "crypto",
        "custom",
        "liability",
    ],
}
MARKET = {"type": "string", "enum": ["US", "HK", "CN", "CRYPTO", "COMMODITY", "OTHER"]}
PRICE_SOURCE = {"type": "string", "enum": ["market", "manual", "fx_derived", "fixed_principal"]}
TRANSACTION_TYPE = {
    "type": "string",
    "enum": [
        "buy",
        "sell",
        "deposit",
        "withdraw",
        "transfer_in",
        "transfer_out",
        "fx_exchange",
        "dividend",
        "interest",
        "fee",
        "manual_adjustment",
        "valuation_update",
    ],
}

TOOL_SCHEMAS = [
    # Owners
    _tool("list_owners", "List all family owners.", {}, [], resource="owner"),
    _tool("search_owner", "Search family owners by name.", {"query": {"type": "string"}}, ["query"], resource="owner"),
    _tool("get_owner", "Get one owner by ID.", {"owner_id": ID}, ["owner_id"], resource="owner"),
    _tool(
        "create_owner",
        "Create a family owner. A person's safe default owner_type is individual.",
        {
            "name": {"type": "string"},
            "owner_type": {"type": "string", "enum": ["individual", "family_entity"]},
            "display_order": {"type": "integer"},
        },
        ["name"],
        effect="create",
        resource="owner",
    ),
    _tool(
        "update_owner",
        "Update an existing family owner.",
        {
            "owner_id": ID,
            "name": {"type": "string"},
            "owner_type": {"type": "string", "enum": ["individual", "family_entity"]},
            "display_order": {"type": "integer"},
        },
        ["owner_id"],
        effect="update",
        resource="owner",
    ),
    _tool(
        "delete_owner",
        "Delete an owner only when no accounts depend on it.",
        {"owner_id": ID},
        ["owner_id"],
        effect="delete",
        resource="owner",
    ),
    # Institutions
    _tool("list_institutions", "List all banks, brokers, and custodians.", {}, [], resource="institution"),
    _tool(
        "search_institution",
        "Search banks, brokers, and custodians by name.",
        {"query": {"type": "string"}},
        ["query"],
        resource="institution",
    ),
    _tool(
        "get_institution",
        "Get one institution by ID.",
        {"institution_id": ID},
        ["institution_id"],
        resource="institution",
    ),
    _tool(
        "create_institution",
        "Create a bank, broker, or other custodian. Leave country unset when the branch country is unknown.",
        {
            "name": {"type": "string"},
            "institution_type": {"type": "string", "enum": ["bank", "broker", "other"]},
            "country": {"type": "string", "minLength": 2, "maxLength": 2},
        },
        ["name", "institution_type"],
        effect="create",
        resource="institution",
    ),
    _tool(
        "update_institution",
        "Update an existing institution.",
        {
            "institution_id": ID,
            "name": {"type": "string"},
            "institution_type": {"type": "string", "enum": ["bank", "broker", "other"]},
            "country": {"type": "string", "minLength": 2, "maxLength": 2},
        },
        ["institution_id"],
        effect="update",
        resource="institution",
    ),
    _tool(
        "delete_institution",
        "Delete an institution only when no accounts depend on it.",
        {"institution_id": ID},
        ["institution_id"],
        effect="delete",
        resource="institution",
    ),
    # Accounts
    _tool("list_accounts", "List all portfolio accounts with owner and institution data.", {}, [], resource="account"),
    _tool(
        "search_account",
        "Search accounts by account, owner, or institution name and optional IDs.",
        {"query": {"type": "string"}, "owner_id": ID, "institution_id": ID},
        [],
        resource="account",
    ),
    _tool("get_account", "Get one account by ID.", {"account_id": ID}, ["account_id"], resource="account"),
    _tool(
        "create_account",
        "Create a portfolio account for an owner and institution. Infer a clear display name instead of asking for one.",
        {
            "name": {"type": "string"},
            "institution_id": ID,
            "owner_id": ID,
            "account_type": ACCOUNT_TYPE,
            "base_currency": CURRENCY,
            "account_number_mask": {"type": "string"},
        },
        ["name", "institution_id", "owner_id", "account_type", "base_currency"],
        effect="create",
        resource="account",
    ),
    _tool(
        "update_account",
        "Update an existing portfolio account.",
        {
            "account_id": ID,
            "name": {"type": "string"},
            "institution_id": ID,
            "owner_id": ID,
            "account_type": ACCOUNT_TYPE,
            "base_currency": CURRENCY,
            "account_number_mask": {"type": "string"},
        },
        ["account_id"],
        effect="update",
        resource="account",
    ),
    _tool(
        "delete_account",
        "Delete an account and its materialized holdings only when no ledger entries depend on it.",
        {"account_id": ID},
        ["account_id"],
        effect="delete",
        resource="account",
    ),
    # Instruments and market data
    _tool("list_instruments", "List all portfolio instruments.", {}, [], resource="instrument"),
    _tool(
        "search_instrument",
        "Search local instruments by name or symbol.",
        {"query": {"type": "string"}},
        ["query"],
        resource="instrument",
    ),
    _tool(
        "search_market_instrument",
        "Search local and external market catalogs by symbol or name.",
        {"query": {"type": "string"}},
        ["query"],
        resource="instrument",
    ),
    _tool(
        "get_instrument",
        "Get one instrument by ID.",
        {"instrument_id": ID},
        ["instrument_id"],
        resource="instrument",
    ),
    _tool(
        "create_instrument",
        "Create a stock, fund, cash, property, crypto, liability, or other instrument.",
        {
            "name": {"type": "string"},
            "symbol": {"type": "string"},
            "asset_class": ASSET_CLASS,
            "currency": CURRENCY,
            "country": {"type": "string", "minLength": 2, "maxLength": 2},
            "market": MARKET,
            "exposure_group_id": ID,
            "price_source_type": PRICE_SOURCE,
        },
        ["name", "asset_class", "currency", "price_source_type"],
        effect="create",
        resource="instrument",
    ),
    _tool(
        "update_instrument",
        "Update fields on an existing instrument.",
        {
            "instrument_id": ID,
            "name": {"type": "string"},
            "symbol": {"type": "string"},
            "currency": CURRENCY,
            "country": {"type": "string", "minLength": 2, "maxLength": 2},
            "market": MARKET,
            "asset_class": ASSET_CLASS,
            "exposure_group_id": ID,
            "price_source_type": PRICE_SOURCE,
        },
        ["instrument_id"],
        effect="update",
        resource="instrument",
    ),
    _tool(
        "delete_instrument",
        "Delete an instrument only when holdings and transactions do not depend on it.",
        {"instrument_id": ID},
        ["instrument_id"],
        effect="delete",
        resource="instrument",
    ),
    _tool(
        "get_latest_price",
        "Get the latest stored price for an instrument.",
        {"instrument_id": ID},
        ["instrument_id"],
        resource="price_snapshot",
    ),
    _tool(
        "get_price_history",
        "Get stored price history for an instrument.",
        {"instrument_id": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 500}},
        ["instrument_id"],
        resource="price_snapshot",
    ),
    _tool(
        "lookup_historical_market_price",
        "Look up the nearest historical market quote for a market instrument at an exact timezone-aware time. This is not the user's actual fill price.",
        {"instrument_id": ID, "as_of": DATETIME},
        ["instrument_id", "as_of"],
        resource="market_quote",
    ),
    # Private family document knowledge. Every service applies the bound family scope.
    _tool(
        "search_documents",
        "Search indexed family documents with hybrid full-text/vector retrieval and page citations.",
        {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "document_ids": {"type": "array", "items": ID, "maxItems": 100},
            "document_types": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
            "date_from": DATE,
            "date_to": DATE,
            "institution_id": ID,
            "account_id": ID,
        },
        ["query"],
        resource="document_chunk",
    ),
    _tool(
        "retrieve_document_chunks",
        "Retrieve indexed chunks from one family document with exact page citations.",
        {
            "document_id": ID,
            "page_number": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        ["document_id"],
        resource="document_chunk",
    ),
    _tool(
        "draft_transactions_from_document",
        "Create a review-only transaction draft from a processed document. This never posts ledger entries.",
        {"document_id": ID},
        ["document_id"],
        effect="create",
        resource="document_extraction",
    ),
    # Exposure groups
    _tool("list_exposure_groups", "List all underlying exposure groups.", {}, [], resource="exposure_group"),
    _tool(
        "get_exposure_group",
        "Get one underlying exposure group by ID.",
        {"exposure_group_id": ID},
        ["exposure_group_id"],
        resource="exposure_group",
    ),
    _tool(
        "create_exposure_group",
        "Create an underlying market exposure group.",
        {"name": {"type": "string"}, "description": {"type": "string"}},
        ["name"],
        effect="create",
        resource="exposure_group",
    ),
    _tool(
        "update_exposure_group",
        "Update an exposure group.",
        {"exposure_group_id": ID, "name": {"type": "string"}, "description": {"type": "string"}},
        ["exposure_group_id"],
        effect="update",
        resource="exposure_group",
    ),
    _tool(
        "delete_exposure_group",
        "Delete an exposure group. Linked instruments will become ungrouped.",
        {"exposure_group_id": ID},
        ["exposure_group_id"],
        effect="delete",
        resource="exposure_group",
    ),
    # Holdings
    _tool(
        "get_holdings",
        "Get current holdings, optionally filtered by account or instrument.",
        {"account_id": ID, "instrument_id": ID},
        [],
        resource="holding",
    ),
    _tool(
        "set_holding_snapshot",
        "Create a reconciliation event that brings a holding projection to an exact quantity.",
        {"account_id": ID, "instrument_id": ID, "quantity": NUMBER},
        ["account_id", "instrument_id", "quantity"],
        effect="update",
        resource="holding",
    ),
    _tool(
        "adjust_holding",
        "Create an auditable reconciliation event with a signed quantity delta.",
        {"account_id": ID, "instrument_id": ID, "delta_quantity": NUMBER},
        ["account_id", "instrument_id", "delta_quantity"],
        effect="update",
        resource="holding",
    ),
    _tool(
        "delete_holding",
        "Reconcile a holding projection to zero; no holding or ledger row is deleted.",
        {"holding_id": ID},
        ["holding_id"],
        effect="update",
        resource="holding",
    ),
    # Transaction reads
    _tool(
        "list_transactions",
        "List ledger transactions with optional filters.",
        {
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            "account_id": ID,
            "instrument_id": ID,
            "transaction_type": TRANSACTION_TYPE,
            "date_from": DATE,
            "date_to": DATE,
        },
        [],
        resource="transaction",
    ),
    _tool(
        "get_transaction",
        "Get one ledger transaction by ID.",
        {"transaction_id": ID},
        ["transaction_id"],
        resource="transaction",
    ),
    # Transaction writes
    _tool(
        "create_buy_transaction",
        "Record a buy and atomically increase the asset holding and decrease cash.",
        {
            "account_id": ID,
            "instrument_id": ID,
            "quantity": NUMBER,
            "price": NUMBER,
            "currency": CURRENCY,
            "fee": NUMBER,
            "fee_currency": CURRENCY,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "settlement_date": DATE,
            "external_ref": {"type": "string"},
            "note": {"type": "string"},
        },
        ["account_id", "instrument_id", "quantity", "price", "currency", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_sell_transaction",
        "Record a sale and atomically decrease the asset holding and increase cash.",
        {
            "account_id": ID,
            "instrument_id": ID,
            "quantity": NUMBER,
            "price": NUMBER,
            "currency": CURRENCY,
            "fee": NUMBER,
            "fee_currency": CURRENCY,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "settlement_date": DATE,
            "external_ref": {"type": "string"},
            "note": {"type": "string"},
        },
        ["account_id", "instrument_id", "quantity", "price", "currency", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_transfer",
        "Transfer an instrument quantity between two internal accounts with linked ledger entries.",
        {
            "from_account_id": ID,
            "to_account_id": ID,
            "instrument_id": ID,
            "quantity": NUMBER,
            "currency": CURRENCY,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "settlement_date": DATE,
            "external_ref": {"type": "string"},
            "note": {"type": "string"},
        },
        ["from_account_id", "to_account_id", "instrument_id", "quantity", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_currency_exchange",
        "Exchange one cash currency for another within an account.",
        {
            "account_id": ID,
            "from_currency": CURRENCY,
            "from_amount": NUMBER,
            "to_currency": CURRENCY,
            "to_amount": NUMBER,
            "rate": NUMBER,
            "fee": NUMBER,
            "fee_currency": CURRENCY,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "note": {"type": "string"},
        },
        ["account_id", "from_currency", "from_amount", "to_currency", "to_amount", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_income_transaction",
        "Record dividend or interest income and increase cash.",
        {
            "account_id": ID,
            "instrument_id": ID,
            "amount": NUMBER,
            "currency": CURRENCY,
            "transaction_type": {"type": "string", "enum": ["dividend", "interest"]},
            "trade_date": DATE,
            "executed_at": DATETIME,
            "note": {"type": "string"},
        },
        ["account_id", "amount", "currency", "transaction_type", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_fee_transaction",
        "Record a standalone fee and decrease cash.",
        {
            "account_id": ID,
            "instrument_id": ID,
            "amount": NUMBER,
            "currency": CURRENCY,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "note": {"type": "string"},
        },
        ["account_id", "amount", "currency", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_cash_transaction",
        "Record a cash deposit or withdrawal.",
        {
            "account_id": ID,
            "amount": NUMBER,
            "currency": CURRENCY,
            "transaction_type": {"type": "string", "enum": ["deposit", "withdraw"]},
            "trade_date": DATE,
            "executed_at": DATETIME,
            "note": {"type": "string"},
        },
        ["account_id", "amount", "currency", "transaction_type", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "create_manual_adjustment",
        "Create an auditable signed quantity adjustment in the transaction ledger.",
        {
            "account_id": ID,
            "instrument_id": ID,
            "delta_quantity": NUMBER,
            "currency": CURRENCY,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "note": {"type": "string"},
        },
        ["account_id", "instrument_id", "delta_quantity", "currency", "trade_date"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "update_transaction_metadata",
        "Append a metadata-amended event. To change economic fields, reverse and recreate.",
        {
            "transaction_id": ID,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "settlement_date": DATE,
            "external_ref": {"type": "string"},
            "note": {"type": "string"},
        },
        ["transaction_id"],
        effect="update",
        resource="transaction",
    ),
    _tool(
        "delete_transaction",
        "Compatibility command that appends reversal events; posted ledger rows are never deleted.",
        {"transaction_id": ID},
        ["transaction_id"],
        effect="create",
        resource="transaction",
    ),
    _tool(
        "reverse_transaction",
        "Create audited reversal entries for a transaction.",
        {"transaction_id": ID},
        ["transaction_id"],
        effect="create",
        resource="transaction",
    ),
    # Cash, valuation, FX, settings, and maintenance
    _tool(
        "set_cash_balance",
        "Set an account's exact cash balance using a replayable ledger adjustment for initialization or reconciliation.",
        {
            "account_id": ID,
            "currency": CURRENCY,
            "balance": NUMBER,
            "trade_date": DATE,
            "executed_at": DATETIME,
            "note": {"type": "string"},
        },
        ["account_id", "currency", "balance"],
        effect="update",
        resource="holding",
    ),
    _tool(
        "set_manual_valuation",
        "Create a manual valuation snapshot for an instrument.",
        {
            "instrument_id": ID,
            "price": NUMBER,
            "currency": CURRENCY,
            "as_of": DATETIME,
            "note": {"type": "string"},
        },
        ["instrument_id", "price", "currency"],
        effect="create",
        resource="price_snapshot",
    ),
    _tool(
        "create_price_snapshot",
        "Create a point-in-time manual price snapshot; this does not alter a holding.",
        {
            "instrument_id": ID,
            "price": NUMBER,
            "currency": CURRENCY,
            "as_of": DATETIME,
            "note": {"type": "string"},
        },
        ["instrument_id", "price", "currency"],
        effect="create",
        resource="price_snapshot",
    ),
    _tool("list_fx_rates", "List the latest stored FX rates.", {}, [], resource="fx_rate_snapshot"),
    _tool(
        "set_fx_rate",
        "Create a manual point-in-time FX rate.",
        {
            "base_currency": CURRENCY,
            "quote_currency": CURRENCY,
            "rate": NUMBER,
            "as_of": DATETIME,
        },
        ["base_currency", "quote_currency", "rate"],
        effect="create",
        resource="fx_rate_snapshot",
    ),
    _tool("get_app_settings", "Get portfolio application settings.", {}, [], resource="app_setting"),
    _tool(
        "update_app_settings",
        "Update the portfolio base currency.",
        {"base_currency": CURRENCY},
        ["base_currency"],
        effect="update",
        resource="app_setting",
    ),
    _tool(
        "refresh_market_prices",
        "Refresh market prices and FX rates and create a valuation snapshot.",
        {},
        [],
        effect="create",
        resource="price_snapshot",
    ),
    _tool(
        "recalculate_portfolio",
        "Rebuild materialized holdings from the transaction ledger.",
        {"account_id": ID},
        [],
        effect="update",
        resource="holding",
    ),
    _tool(
        "create_valuation_snapshot",
        "Save the portfolio's current total and allocation history point.",
        {},
        [],
        effect="create",
        resource="valuation_snapshot",
    ),
    _tool(
        "list_valuation_snapshots",
        "List saved whole-portfolio valuation snapshots.",
        {
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        [],
        resource="valuation_snapshot",
    ),
    _tool(
        "get_latest_valuation_snapshot",
        "Get the latest saved whole-portfolio valuation snapshot.",
        {},
        [],
        resource="valuation_snapshot",
    ),
]

MUTATING_TOOL_NAMES = frozenset(name for name, effect in TOOL_EFFECTS.items() if effect != "read")
RESERVED_ID_TOOLS = frozenset(
    {
        "create_owner",
        "create_institution",
        "create_account",
        "create_instrument",
        "create_exposure_group",
    }
)


def tool_requires_confirmation(name: str) -> bool:
    if name not in TOOL_EFFECTS:
        raise ValueError("unknown_agent_tool")
    return name in MUTATING_TOOL_NAMES


def prepare_pending_tool_call(
    name: str,
    args: dict[str, Any],
    confirmation_id: uuid.UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not tool_requires_confirmation(name):
        raise ValueError("read_tool_cannot_be_staged")
    stored_args = dict(args)
    # Persist one opaque retry token with the staged command. Confirmation can
    # then be retried safely after an ambiguous transport or worker failure.
    stored_args["_idempotency_key"] = f"agent:{confirmation_id}:{uuid.uuid4()}"
    preview: dict[str, Any] = {
        "status": "pending_confirmation",
        "confirmation_id": str(confirmation_id),
        "effect": TOOL_EFFECTS[name],
        "resource": TOOL_RESOURCES[name],
    }
    if name in RESERVED_ID_TOOLS:
        reserved_id = uuid.uuid4()
        stored_args["_record_id"] = str(reserved_id)
        preview["id"] = str(reserved_id)
        preview["reserved_id"] = str(reserved_id)
    return stored_args, preview


def public_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if not key.startswith("_")}


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    return value if isinstance(value, date) else date.fromisoformat(value)


def _datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _result(value: Any) -> Any:
    return json_value(value)


async def dispatch_tool(
    db: AsyncSession,
    name: str,
    args: dict[str, Any],
    *,
    commit: bool = True,
) -> Any:
    args = dict(args)
    record_id = _uuid(args.pop("_record_id")) if args.get("_record_id") else None
    idempotency_key = args.pop("_idempotency_key", None)

    # Read-only tools.
    if name == "list_owners":
        return _result(await owner_service.list_owners(db))
    if name == "search_owner":
        return _result(await owner_service.search_owners(db, args["query"]))
    if name == "get_owner":
        row = await owner_service.get_owner(db, _uuid(args["owner_id"]))
        if row is None:
            raise ValueError("owner_not_found")
        return _result(row)
    if name == "list_institutions":
        return _result(await institution_service.list_institutions(db))
    if name == "search_institution":
        return _result(await institution_service.search_institutions(db, args["query"]))
    if name == "get_institution":
        row = await institution_service.get_institution(db, _uuid(args["institution_id"]))
        if row is None:
            raise ValueError("institution_not_found")
        return _result(row)
    if name == "list_accounts":
        return _result(await account_service.list_accounts(db))
    if name == "search_account":
        stmt = (
            select(Account)
            .join(Account.institution)
            .join(Account.owner)
            .options(selectinload(Account.institution), selectinload(Account.owner))
            .limit(50)
        )
        query = str(args.get("query") or "").strip()
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Account.name.ilike(like),
                    Institution.name.ilike(like),
                    Owner.name.ilike(like),
                )
            )
        if args.get("owner_id"):
            stmt = stmt.where(Account.owner_id == _uuid(args["owner_id"]))
        if args.get("institution_id"):
            stmt = stmt.where(Account.institution_id == _uuid(args["institution_id"]))
        return _result(list((await db.execute(stmt)).scalars().unique()))
    if name == "get_account":
        row = await account_service.get_account(db, _uuid(args["account_id"]))
        if row is None:
            raise ValueError("account_not_found")
        return _result(row)
    if name == "list_instruments":
        return _result(await instrument_service.list_instruments(db))
    if name == "search_instrument":
        return _result(await instrument_service.search_instruments(db, args["query"]))
    if name == "search_market_instrument":
        return _result(await market_instrument_service.search_market_instruments(db, args["query"]))
    if name == "get_instrument":
        row = await instrument_service.get_instrument(db, _uuid(args["instrument_id"]))
        if row is None:
            raise ValueError("instrument_not_found")
        return _result(row)
    if name == "get_latest_price":
        row = await valuation_service.get_latest_price(db, _uuid(args["instrument_id"]))
        return _result(row)
    if name == "get_price_history":
        rows = await valuation_service.list_price_history(
            db,
            _uuid(args["instrument_id"]),
            int(args.get("limit", 30)),
        )
        return _result(rows)
    if name == "lookup_historical_market_price":
        return _result(
            await market_price_history_service.lookup_historical_market_price(
                db,
                _uuid(args["instrument_id"]),
                _datetime(args["as_of"]),
            )
        )
    if name == "search_documents":
        query = str(args.pop("query"))
        filters = KnowledgeFilters.model_validate(args)
        return (
            await knowledge_service.search_knowledge(db, query, filters)
        ).model_dump(mode="json")
    if name == "retrieve_document_chunks":
        return await knowledge_service.retrieve_document_chunks(
            db,
            _uuid(args["document_id"]),
            page_number=int(args["page_number"]) if args.get("page_number") else None,
            limit=int(args.get("limit", 20)),
        )
    if name == "list_exposure_groups":
        return _result(await exposure_group_service.list_exposure_groups(db))
    if name == "get_exposure_group":
        row = await family_scoped_get(db, ExposureGroup, _uuid(args["exposure_group_id"]))
        if row is None:
            raise ValueError("exposure_group_not_found")
        return _result(row)
    if name == "get_holdings":
        stmt = select(Holding).options(selectinload(Holding.instrument), selectinload(Holding.account))
        if args.get("account_id"):
            stmt = stmt.where(Holding.account_id == _uuid(args["account_id"]))
        if args.get("instrument_id"):
            stmt = stmt.where(Holding.instrument_id == _uuid(args["instrument_id"]))
        return _result(list((await db.execute(stmt)).scalars()))
    if name == "list_transactions":
        rows, total, summary = await transaction_service.list_transactions(
            db,
            int(args.get("offset", 0)),
            int(args.get("limit", 100)),
            _uuid(args["account_id"]) if args.get("account_id") else None,
            TransactionType(args["transaction_type"]) if args.get("transaction_type") else None,
            _date(args["date_from"]) if args.get("date_from") else None,
            _date(args["date_to"]) if args.get("date_to") else None,
            _uuid(args["instrument_id"]) if args.get("instrument_id") else None,
        )
        return {"items": _result(rows), "total": total, "summary": _result(summary)}
    if name == "get_transaction":
        row = await transaction_service.get_transaction(db, _uuid(args["transaction_id"]))
        if row is None:
            raise ValueError("transaction_not_found")
        return _result(row)
    if name == "list_fx_rates":
        return _result(await valuation_service.list_latest_fx_rates(db))
    if name == "get_app_settings":
        return {
            "base_currency": await settings_service.get_base_currency(
                db,
                settings.default_base_currency,
            )
        }
    if name == "list_valuation_snapshots":
        rows, total = await valuation_snapshot_service.list_valuation_snapshots(
            db,
            int(args.get("offset", 0)),
            int(args.get("limit", 100)),
        )
        return {"items": _result(rows), "total": total}
    if name == "get_latest_valuation_snapshot":
        return _result(await valuation_snapshot_service.get_latest_valuation_snapshot(db))

    # Mutating tools. The agent orchestrator stages every one of these before dispatch.
    if name == "create_owner":
        return _result(
            await owner_service.create_owner(
                db,
                OwnerCreate(**args),
                record_id=record_id,
                commit=commit,
            )
        )
    if name == "draft_transactions_from_document":
        draft = await document_draft_service.create_transaction_draft(
            db,
            _uuid(args["document_id"]),
            commit=commit,
        )
        return document_draft_service.draft_schema(draft).model_dump(mode="json")
    if name == "update_owner":
        owner_id = _uuid(args.pop("owner_id"))
        row = await owner_service.update_owner(db, owner_id, OwnerUpdate(**args), commit=commit)
        if row is None:
            raise ValueError("owner_not_found")
        return _result(row)
    if name == "delete_owner":
        if not await owner_service.delete_owner(db, _uuid(args["owner_id"]), commit=commit):
            raise ValueError("owner_not_found")
        return {"deleted_id": str(args["owner_id"])}
    if name == "create_institution":
        return _result(
            await institution_service.create_institution(
                db,
                InstitutionCreate(**args),
                record_id=record_id,
                commit=commit,
            )
        )
    if name == "update_institution":
        institution_id = _uuid(args.pop("institution_id"))
        row = await institution_service.update_institution(
            db,
            institution_id,
            InstitutionUpdate(**args),
            commit=commit,
        )
        if row is None:
            raise ValueError("institution_not_found")
        return _result(row)
    if name == "delete_institution":
        if not await institution_service.delete_institution(
            db,
            _uuid(args["institution_id"]),
            commit=commit,
        ):
            raise ValueError("institution_not_found")
        return {"deleted_id": str(args["institution_id"])}
    if name == "create_account":
        return _result(
            await account_service.create_account(
                db,
                AccountCreate(**args),
                record_id=record_id,
                commit=commit,
            )
        )
    if name == "update_account":
        account_id = _uuid(args.pop("account_id"))
        row = await account_service.update_account(db, account_id, AccountUpdate(**args), commit=commit)
        if row is None:
            raise ValueError("account_not_found")
        return _result(row)
    if name == "delete_account":
        if not await account_service.delete_account(db, _uuid(args["account_id"]), commit=commit):
            raise ValueError("account_not_found")
        return {"deleted_id": str(args["account_id"])}
    if name == "create_instrument":
        return _result(
            await instrument_service.create_instrument(
                db,
                InstrumentCreate(**args),
                record_id=record_id,
                commit=commit,
            )
        )
    if name == "update_instrument":
        instrument_id = _uuid(args.pop("instrument_id"))
        row = await instrument_service.update_instrument(
            db,
            instrument_id,
            InstrumentUpdate(**args),
            commit=commit,
        )
        if row is None:
            raise ValueError("instrument_not_found")
        return _result(row)
    if name == "delete_instrument":
        if not await instrument_service.delete_instrument(
            db,
            _uuid(args["instrument_id"]),
            commit=commit,
        ):
            raise ValueError("instrument_not_found")
        return {"deleted_id": str(args["instrument_id"])}
    if name == "create_exposure_group":
        return _result(
            await exposure_group_service.create_exposure_group(
                db,
                ExposureGroupCreate(**args),
                record_id=record_id,
                commit=commit,
            )
        )
    if name == "update_exposure_group":
        group_id = _uuid(args.pop("exposure_group_id"))
        row = await exposure_group_service.update_exposure_group(
            db,
            group_id,
            ExposureGroupUpdate(**args),
            commit=commit,
        )
        if row is None:
            raise ValueError("exposure_group_not_found")
        return _result(row)
    if name == "delete_exposure_group":
        if not await exposure_group_service.delete_exposure_group(
            db,
            _uuid(args["exposure_group_id"]),
            commit=commit,
        ):
            raise ValueError("exposure_group_not_found")
        return {"deleted_id": str(args["exposure_group_id"])}
    if name == "set_holding_snapshot":
        row = await holding_service.set_holding_snapshot(
            db,
            _uuid(args["account_id"]),
            _uuid(args["instrument_id"]),
            Decimal(str(args["quantity"])),
            HoldingSource.AGENT,
            commit=commit,
            idempotency_key=idempotency_key,
        )
        return _result(row)
    if name == "adjust_holding":
        row = await holding_service.adjust_holding(
            db,
            _uuid(args["account_id"]),
            _uuid(args["instrument_id"]),
            Decimal(str(args["delta_quantity"])),
            HoldingSource.AGENT,
            commit=commit,
            idempotency_key=idempotency_key,
        )
        return _result(row)
    if name == "delete_holding":
        row = await holding_service.reconcile_holding_to_zero(
            db,
            _uuid(args["holding_id"]),
            HoldingSource.AGENT,
            commit=commit,
            idempotency_key=idempotency_key,
        )
        return {
            "reconciled_holding_id": str(row.id),
            "quantity": str(row.quantity),
            "event_ids": [str(row.last_event_id)] if row.last_event_id else [],
        }
    if name in ("create_buy_transaction", "create_sell_transaction"):
        payload_data = {
            **args,
            "source": TransactionSource.AGENT,
            "trade_date": _date(args.get("trade_date")),
            "executed_at": _datetime(args.get("executed_at")),
        }
        if name == "create_buy_transaction":
            tx = await transaction_service.create_buy_transaction(
                db,
                BuyTransactionCreate(**payload_data),
                commit=commit,
                idempotency_key=idempotency_key,
            )
        else:
            tx = await transaction_service.create_sell_transaction(
                db,
                SellTransactionCreate(**payload_data),
                commit=commit,
                idempotency_key=idempotency_key,
            )
        return _result(tx)
    if name == "create_transfer":
        instrument = await instrument_service.get_instrument(db, _uuid(args["instrument_id"]))
        if instrument is None:
            raise ValueError("instrument_not_found")
        payload = TransferCreate(
            **{
                **args,
                "currency": args.get("currency") or instrument.currency,
                "source": TransactionSource.AGENT,
                "trade_date": _date(args.get("trade_date")),
                "executed_at": _datetime(args.get("executed_at")),
            }
        )
        return _result(
            await transaction_service.create_transfer(
                db,
                payload,
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "create_currency_exchange":
        payload = FXExchangeCreate(
            **{
                **args,
                "source": TransactionSource.AGENT,
                "trade_date": _date(args.get("trade_date")),
                "executed_at": _datetime(args.get("executed_at")),
            }
        )
        return _result(
            await transaction_service.create_currency_exchange(
                db,
                payload,
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "create_income_transaction":
        payload = IncomeTransactionCreate(
            **{
                **args,
                "source": TransactionSource.AGENT,
                "trade_date": _date(args.get("trade_date")),
                "executed_at": _datetime(args.get("executed_at")),
            }
        )
        return _result(
            await transaction_service.create_income_transaction(
                db,
                payload,
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "create_fee_transaction":
        payload = FeeTransactionCreate(
            **{
                **args,
                "source": TransactionSource.AGENT,
                "trade_date": _date(args.get("trade_date")),
                "executed_at": _datetime(args.get("executed_at")),
            }
        )
        return _result(
            await transaction_service.create_fee_transaction(
                db,
                payload,
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "create_cash_transaction":
        payload = CashTransactionCreate(
            **{
                **args,
                "source": TransactionSource.AGENT,
                "trade_date": _date(args.get("trade_date")),
                "executed_at": _datetime(args.get("executed_at")),
            }
        )
        return _result(
            await transaction_service.create_cash_transaction(
                db,
                payload,
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "create_manual_adjustment":
        payload = ManualAdjustmentCreate(
            **{
                **args,
                "source": TransactionSource.AGENT,
                "trade_date": _date(args.get("trade_date")),
                "executed_at": _datetime(args.get("executed_at")),
            }
        )
        return _result(
            await transaction_service.create_manual_adjustment(
                db,
                payload,
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "update_transaction_metadata":
        transaction_id = _uuid(args.pop("transaction_id"))
        rows = await transaction_service.update_transaction_metadata(
            db,
            transaction_id,
            TransactionMetadataUpdate(**args),
            commit=commit,
            idempotency_key=idempotency_key,
        )
        return _result(rows)
    if name == "delete_transaction":
        return {
            "reversal_event_ids": [
                str(value)
                for value in await transaction_service.delete_transaction(
                    db,
                    _uuid(args["transaction_id"]),
                    commit=commit,
                    idempotency_key=idempotency_key,
                )
            ]
        }
    if name == "reverse_transaction":
        return _result(
            await transaction_service.reverse_transaction(
                db,
                _uuid(args["transaction_id"]),
                commit=commit,
                idempotency_key=idempotency_key,
            )
        )
    if name == "set_cash_balance":
        account_id = _uuid(args["account_id"])
        currency = str(args["currency"]).upper()
        target_balance = Decimal(str(args["balance"]))
        await transaction_service._require_account(db, account_id)
        cash = await transaction_service._cash_instrument(db, currency)
        holding = await holding_service.get_holding(db, account_id, cash.id)
        previous_balance = holding.quantity if holding is not None else Decimal(0)
        adjustment = target_balance - previous_balance
        transaction = await transaction_service.create_reconciliation_transaction(
            db,
            account_id,
            cash.id,
            currency,
            TransactionSource.AGENT,
            target_quantity=target_balance,
            commit=commit,
            idempotency_key=idempotency_key,
            metadata={"compatibility_command": "agent set_cash_balance"},
            note=args.get("note")
            or f"Cash balance reconciled to {target_balance} {currency}",
        )
        return {
            "account_id": str(account_id),
            "instrument_id": str(cash.id),
            "currency": currency,
            "previous_balance": str(previous_balance),
            "balance": str(target_balance),
            "adjustment": str(adjustment),
            "transaction": _result(transaction),
        }
    if name in ("set_manual_valuation", "create_price_snapshot"):
        await transaction_service._require_instrument(db, _uuid(args["instrument_id"]))
        row = await valuation_service.set_manual_valuation(
            db,
            _uuid(args["instrument_id"]),
            Decimal(str(args["price"])),
            args["currency"],
            _datetime(args.get("as_of")),
            args.get("note"),
            commit=commit,
        )
        return _result(row)
    if name == "set_fx_rate":
        return _result(
            await valuation_service.set_fx_rate(
                db,
                args["base_currency"],
                args["quote_currency"],
                Decimal(str(args["rate"])),
                _datetime(args.get("as_of")),
                source_provider="agent",
                commit=commit,
            )
        )
    if name == "update_app_settings":
        row = await settings_service.set_setting(
            db,
            settings_service.BASE_CURRENCY_KEY,
            str(args["base_currency"]).upper(),
            commit=commit,
        )
        return _result(row)
    if name == "refresh_market_prices":
        return await price_refresh_service.refresh_all_prices(db, commit=commit)
    if name == "recalculate_portfolio":
        return {
            "transaction_count": await transaction_service.recalculate_holdings_from_ledger(
                db,
                _uuid(args["account_id"]) if args.get("account_id") else None,
                commit=commit,
            )
        }
    if name == "create_valuation_snapshot":
        base_currency = await settings_service.get_base_currency(db, settings.default_base_currency)
        return _result(
            await valuation_snapshot_service.create_valuation_snapshot(
                db,
                base_currency,
                commit=commit,
            )
        )
    raise ValueError("unknown_agent_tool")
