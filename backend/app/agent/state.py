import enum
import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import require_bound_family_id
from app.models import (
    Account,
    AppSetting,
    Document,
    ExposureGroup,
    FXRateSnapshot,
    Holding,
    Institution,
    Instrument,
    Owner,
    PriceSnapshot,
    Transaction,
    ValuationSnapshot,
)
from app.models.enums import AssetClass

STATE_MODELS = {
    "owners": Owner,
    "institutions": Institution,
    "exposure_groups": ExposureGroup,
    "accounts": Account,
    "instruments": Instrument,
    "holdings": Holding,
    "transactions": Transaction,
    "price_snapshots": PriceSnapshot,
    "fx_rate_snapshots": FXRateSnapshot,
    "valuation_snapshots": ValuationSnapshot,
    "app_settings": AppSetting,
}

RESOURCE_ID_MODELS = {
    "owner_id": Owner,
    "institution_id": Institution,
    "account_id": Account,
    "from_account_id": Account,
    "to_account_id": Account,
    "instrument_id": Instrument,
    "exposure_group_id": ExposureGroup,
    "holding_id": Holding,
    "transaction_id": Transaction,
    "document_id": Document,
}

CREATE_TOOL_MODELS = {
    "create_owner": Owner,
    "create_institution": Institution,
    "create_account": Account,
    "create_instrument": Instrument,
    "create_exposure_group": ExposureGroup,
}


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if hasattr(value, "__table__"):
        return row_to_dict(value)
    return str(value)


def row_to_dict(row: Any) -> dict[str, Any]:
    return {column.name: json_value(getattr(row, column.name)) for column in row.__table__.columns}


def row_key(row: Any) -> str:
    primary_key = next(iter(row.__table__.primary_key.columns))
    return str(getattr(row, primary_key.name))


async def capture_state(db: AsyncSession) -> dict[str, dict[str, dict[str, Any]]]:
    state: dict[str, dict[str, dict[str, Any]]] = {}
    for table_name, model in STATE_MODELS.items():
        rows = list(
            (
                await db.execute(
                    select(model).execution_options(populate_existing=True)
                )
            ).scalars().all()
        )
        state[table_name] = {row_key(row): row_to_dict(row) for row in rows}
    return state


def state_fingerprint(state: dict[str, dict[str, dict[str, Any]]]) -> str:
    payload = json.dumps(json_value(state), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _version_token(row: Any) -> dict[str, Any]:
    token: dict[str, Any] = {"exists": row is not None}
    if row is None:
        return token
    if isinstance(row, Holding):
        token.update(
            {
                "projection_version": row.projection_version,
                "last_event_id": json_value(row.last_event_id),
            }
        )
    elif isinstance(row, Transaction):
        token.update(
            {
                "event_version": row.event_version,
                "is_reversed": row.is_reversed,
                "reversed_by_id": json_value(row.reversed_by_id),
            }
        )
    if hasattr(row, "updated_at"):
        token["updated_at"] = json_value(row.updated_at)
    return token


def _call_args(call: dict[str, Any]) -> dict[str, Any]:
    return dict(call.get("_dispatch_args") or call.get("args") or {})


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


async def _add_model_token(
    db: AsyncSession,
    expected: dict[str, dict[str, Any]],
    model: Any,
    object_id: uuid.UUID,
) -> None:
    key = f"{model.__tablename__}:{object_id}"
    if key in expected:
        return
    family_id = require_bound_family_id(db)
    row = (
        await db.execute(
            select(model)
            .where(
                model.id == object_id,
                model.family_id == family_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    expected[key] = _version_token(row)


async def _cash_holding_token(
    db: AsyncSession,
    expected: dict[str, dict[str, Any]],
    account_id: uuid.UUID,
    currency: str,
) -> None:
    code = currency.upper()
    instrument = (
        await db.execute(
            select(Instrument)
            .where(
                Instrument.asset_class == AssetClass.CASH,
                Instrument.currency == code,
                Instrument.symbol == code,
            )
            .with_for_update()
            .limit(1)
        )
    ).scalar_one_or_none()
    key = f"cash_holdings:{account_id}:{code}"
    if instrument is None:
        expected[key] = {"exists": False}
        return
    holding = (
        await db.execute(
            select(Holding)
            .where(
                Holding.account_id == account_id,
                Holding.instrument_id == instrument.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    expected[key] = {
        **_version_token(holding),
        "instrument_id": str(instrument.id),
    }


async def _position_holding_token(
    db: AsyncSession,
    expected: dict[str, dict[str, Any]],
    account_id: uuid.UUID,
    instrument_id: uuid.UUID,
) -> None:
    key = f"position_holdings:{account_id}:{instrument_id}"
    holding = (
        await db.execute(
            select(Holding)
            .where(
                Holding.account_id == account_id,
                Holding.instrument_id == instrument_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    expected[key] = _version_token(holding)


async def _add_holding_tokens(
    db: AsyncSession,
    expected: dict[str, dict[str, Any]],
    tool_name: str,
    args: dict[str, Any],
) -> None:
    instrument_id = _uuid_or_none(args.get("instrument_id"))
    account_ids: list[uuid.UUID] = []
    for key in ("account_id", "from_account_id", "to_account_id"):
        value = _uuid_or_none(args.get(key))
        if value is not None and value not in account_ids:
            account_ids.append(value)
    if instrument_id is not None:
        for account_id in account_ids:
            await _position_holding_token(
                db,
                expected,
                account_id,
                instrument_id,
            )

    cash_currencies: list[str] = []
    if tool_name in {
        "create_buy_transaction",
        "create_sell_transaction",
        "create_income_transaction",
        "create_fee_transaction",
        "create_cash_transaction",
        "set_cash_balance",
    }:
        if args.get("currency"):
            cash_currencies.append(str(args["currency"]))
        if args.get("fee_currency"):
            cash_currencies.append(str(args["fee_currency"]))
    elif tool_name == "create_currency_exchange":
        for key in ("from_currency", "to_currency", "fee_currency"):
            if args.get(key):
                cash_currencies.append(str(args[key]))
    if cash_currencies:
        account_id = _uuid_or_none(args.get("account_id"))
        if account_id is not None:
            for currency in dict.fromkeys(cash_currencies):
                await _cash_holding_token(
                    db,
                    expected,
                    account_id,
                    currency,
                )


async def collect_expected_versions(
    db: AsyncSession,
    calls: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Capture only rows a staged Agent plan can read or mutate.

    Each token is re-read under row locks immediately before confirmation. This
    replaces the previous O(all portfolio rows × tool calls) snapshot.
    """

    expected: dict[str, dict[str, Any]] = {}
    for call in calls:
        tool_name = str(call.get("tool") or "")
        args = _call_args(call)
        for argument, model in RESOURCE_ID_MODELS.items():
            object_id = _uuid_or_none(args.get(argument))
            if object_id is not None:
                await _add_model_token(db, expected, model, object_id)

        record_id = _uuid_or_none(args.get("_record_id"))
        create_model = CREATE_TOOL_MODELS.get(tool_name)
        if record_id is not None and create_model is not None:
            await _add_model_token(db, expected, create_model, record_id)

        await _add_holding_tokens(db, expected, tool_name, args)

        if tool_name == "update_app_settings":
            family_id = require_bound_family_id(db)
            row = (
                await db.execute(
                    select(AppSetting)
                    .where(
                        AppSetting.family_id == family_id,
                        AppSetting.key == "base_currency",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            expected["app_settings:base_currency"] = {
                "exists": row is not None,
                "value": row.value if row is not None else None,
            }

        if tool_name in {"refresh_market_prices", "recalculate_portfolio"}:
            transaction_count, transaction_updated = (
                await db.execute(
                    select(
                        func.count(Transaction.id),
                        func.max(Transaction.updated_at),
                    )
                )
            ).one()
            holding_count, holding_updated = (
                await db.execute(
                    select(
                        func.count(Holding.id),
                        func.max(Holding.updated_at),
                    )
                )
            ).one()
            expected["portfolio_aggregate:all"] = {
                "transaction_count": int(transaction_count),
                "transaction_updated_at": json_value(transaction_updated),
                "holding_count": int(holding_count),
                "holding_updated_at": json_value(holding_updated),
            }
    return expected


def diff_states(
    before: dict[str, dict[str, dict[str, Any]]],
    after: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    before_diff: dict[str, dict[str, Any]] = {}
    after_diff: dict[str, dict[str, Any]] = {}
    for table_name in STATE_MODELS:
        before_rows = before.get(table_name, {})
        after_rows = after.get(table_name, {})
        changed_ids = {
            row_id
            for row_id in before_rows.keys() | after_rows.keys()
            if before_rows.get(row_id) != after_rows.get(row_id)
        }
        if not changed_ids:
            continue
        before_diff[table_name] = {row_id: before_rows.get(row_id) for row_id in changed_ids}
        after_diff[table_name] = {row_id: after_rows.get(row_id) for row_id in changed_ids}
    return before_diff, after_diff


def summarize_diff(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, int]:
    created = updated = deleted = 0
    for table_name in STATE_MODELS:
        before_rows = before.get(table_name, {})
        after_rows = after.get(table_name, {})
        for row_id in before_rows.keys() | after_rows.keys():
            old, new = before_rows.get(row_id), after_rows.get(row_id)
            if old is None and new is not None:
                created += 1
            elif old is not None and new is None:
                deleted += 1
            elif old != new:
                updated += 1
    return {"created": created, "updated": updated, "deleted": deleted}
