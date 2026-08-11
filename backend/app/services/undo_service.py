"""Compensating undo for Agent-created economic events.

The legacy implementation restored arbitrary historical row snapshots and
could overwrite legitimate changes made after an Agent operation. Undo now
appends reversal events only; non-ledger CRUD is intentionally not rewound.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import family_scoped_get
from app.models import AgentOperationLog, Transaction
from app.services import transaction_service


def _compensation_order(log: AgentOperationLog) -> list[uuid.UUID]:
    """Return original execution order, including compatibility for old logs.

    Current logs store ``event_ids_json`` in tool execution order. Older
    releases sorted that field by UUID, but their redacted tool trace retained
    call order. Use the trace only when it describes exactly the same event
    set, then compensate in reverse at the caller.
    """

    try:
        stored = [uuid.UUID(str(value)) for value in (log.event_ids_json or [])]
    except (TypeError, ValueError) as exc:
        raise ValueError("agent_operation_event_ids_invalid") from exc
    stored = list(dict.fromkeys(stored))
    if not stored:
        raise ValueError("agent_operation_not_compensatable")

    try:
        traced = [
            uuid.UUID(str(value))
            for item in (log.tool_calls_json or [])
            for value in (item.get("event_ids") or [])
        ]
    except (AttributeError, TypeError, ValueError):
        traced = []
    traced = list(dict.fromkeys(traced))
    if traced and set(traced) == set(stored):
        return traced
    if len(stored) == 1:
        return stored
    summary = log.summary_json if isinstance(log.summary_json, dict) else {}
    if summary.get("event_order") == "tool_execution_v1":
        return stored
    raise ValueError("agent_operation_event_order_unknown")


async def undo_agent_operation(
    db: AsyncSession,
    log_id: uuid.UUID,
) -> AgentOperationLog:
    log = await family_scoped_get(db, AgentOperationLog, log_id)
    if log is None:
        raise ValueError("agent_operation_log_not_found")
    if log.operation_type == "undo":
        raise ValueError("undo_cannot_be_undone")
    if log.is_undone:
        raise ValueError("agent_operation_already_undone")
    summary = log.summary_json if isinstance(log.summary_json, dict) else {}
    if summary.get("compensatable") is False:
        raise ValueError("agent_operation_not_compensatable")

    event_ids = _compensation_order(log)

    event_rows = list(
        (
            await db.execute(
                select(Transaction)
                .where(Transaction.id.in_(event_ids))
                # Acquire locks in one deterministic order, while applying
                # compensation below in the reverse of the recorded execution
                # order.
                .order_by(Transaction.id)
                .with_for_update()
            )
        ).scalars()
    )
    if len(event_rows) != len(event_ids):
        raise ValueError("agent_operation_events_changed")
    events_by_id = {event.id: event for event in event_rows}
    events = [events_by_id[event_id] for event_id in reversed(event_ids)]
    if any(event.reversal_of_id is not None for event in events):
        raise ValueError("agent_reversal_operation_not_undoable")
    if any(event.is_reversed for event in events):
        raise ValueError("agent_operation_events_changed")

    processed: set[uuid.UUID] = set()
    reversal_ids: list[str] = []
    try:
        for event in events:
            if event.id in processed:
                continue
            reversals = await transaction_service.reverse_transaction(
                db,
                event.id,
                commit=False,
                idempotency_key=f"agent-undo:{log.id}:{event.id}",
            )
            reversal_ids.extend(str(row.id) for row in reversals)
            processed.add(event.id)
            if event.linked_transaction_id is not None:
                processed.add(event.linked_transaction_id)

        now = datetime.now(timezone.utc)
        log.is_undone = True
        log.undone_at = now
        undo_log = AgentOperationLog(
            session_id=log.session_id,
            turn_index=log.turn_index,
            user_message=f"Compensate operation {log.id}",
            operation_type="undo",
            description=f"Compensating reversal for {log.description}",
            tool_calls_json=[
                {
                    "tool": "reverse_transaction",
                    "effect": "create",
                    "resource": "transaction",
                    "status": "completed",
                    "event_ids": reversal_ids,
                }
            ],
            before_state_json={},
            after_state_json={},
            event_ids_json=reversal_ids,
            summary_json={
                "operation_count": 1,
                "effects": {"create": 1},
                "resources": ["transaction"],
                "event_count": len(reversal_ids),
                "compensates_log_id": str(log.id),
            },
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
