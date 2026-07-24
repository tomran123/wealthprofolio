import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import STATE_MODELS
from app.models import AgentOperationLog

DELETE_ORDER = [
    "transactions",
    "price_snapshots",
    "holdings",
    "accounts",
    "instruments",
    "exposure_groups",
    "institutions",
    "owners",
    "fx_rate_snapshots",
    "valuation_snapshots",
    "app_settings",
]
RESTORE_ORDER = [
    "owners",
    "institutions",
    "exposure_groups",
    "instruments",
    "accounts",
    "holdings",
    "price_snapshots",
    "fx_rate_snapshots",
    "transactions",
    "valuation_snapshots",
    "app_settings",
]


def _deserialize(column: Any, value: Any) -> Any:
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return value
    if python_type is uuid.UUID:
        return uuid.UUID(str(value))
    if python_type is Decimal:
        return Decimal(str(value))
    if python_type is datetime:
        return datetime.fromisoformat(str(value))
    if python_type is date:
        return date.fromisoformat(str(value))
    if isinstance(python_type, type) and issubclass(python_type, enum.Enum):
        return python_type(value)
    return value


def _model_values(model: Any, row: dict[str, Any]) -> dict[str, Any]:
    return {
        column.name: _deserialize(column, row[column.name])
        for column in model.__table__.columns
        if column.name in row
    }


def _primary_key_value(model: Any, row_id: str) -> Any:
    primary_key = next(iter(model.__table__.primary_key.columns))
    return _deserialize(primary_key, row_id)


async def undo_agent_operation(db: AsyncSession, log_id: uuid.UUID) -> AgentOperationLog:
    log = await db.get(AgentOperationLog, log_id)
    if log is None:
        raise ValueError("agent_operation_log_not_found")
    if log.operation_type == "undo":
        raise ValueError("undo_cannot_be_undone")
    if not (log.before_state_json or log.after_state_json):
        raise ValueError("agent_operation_not_undoable")
    if log.is_undone:
        raise ValueError("agent_operation_already_undone")

    before = log.before_state_json or {}
    after = log.after_state_json or {}
    try:
        # Remove records created by the original operation, children first.
        for table_name in DELETE_ORDER:
            model = STATE_MODELS[table_name]
            before_rows = before.get(table_name, {})
            after_rows = after.get(table_name, {})
            for row_id, after_row in after_rows.items():
                if before_rows.get(row_id) is None and after_row is not None:
                    current = await db.get(model, _primary_key_value(model, row_id))
                    if current is not None:
                        await db.delete(current)
        await db.flush()

        # Restore deleted/modified rows to their exact previous values.
        for table_name in RESTORE_ORDER:
            model = STATE_MODELS[table_name]
            before_rows = before.get(table_name, {})
            for row_id, before_row in before_rows.items():
                if before_row is None:
                    continue
                values = _model_values(model, before_row)
                current = await db.get(model, _primary_key_value(model, row_id))
                if current is None:
                    db.add(model(**values))
                else:
                    for field, value in values.items():
                        setattr(current, field, value)
        await db.flush()

        now = datetime.now(timezone.utc)
        log.is_undone = True
        log.undone_at = now
        undo_log = AgentOperationLog(
            session_id=log.session_id,
            turn_index=log.turn_index,
            user_message=f"Undo operation {log.id}",
            operation_type="undo",
            description=f"Undo: {log.description}",
            tool_calls_json=[{"tool": "undo_agent_operation", "args": {"log_id": str(log.id)}}],
            before_state_json=after,
            after_state_json=before,
            is_undone=False,
            linked_to_id=log.id,
        )
        db.add(undo_log)
        await db.commit()
        await db.refresh(log)
        return log
    except Exception:
        await db.rollback()
        raise
