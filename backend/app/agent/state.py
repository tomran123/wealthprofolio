import enum
import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AppSetting,
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
