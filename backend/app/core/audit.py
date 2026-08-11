"""Automatic, append-only audit coverage for family-owned ORM aggregates."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.family_scope import REQUEST_CONTEXT_INFO_KEY, RequestContext
from app.models.base import FamilyScopedMixin
from app.models.ledger import AuditEvent, JournalEntry, JournalPosting, OutboxEvent

# Ledger writes emit a richer domain audit record in transaction_service.  The
# projection and ledger internals are therefore excluded from the generic CRUD
# audit to avoid duplicate/noisy entries.
_DOMAIN_AUDITED_TYPES = {
    "Holding",
    "Transaction",
    JournalEntry.__name__,
    JournalPosting.__name__,
    OutboxEvent.__name__,
}
# Page/chunk rows and progress heartbeats are derived/operational state. Auditing
# each one would create thousands of low-value events per document and make the
# append-only audit log itself a denial-of-service vector. The owning Document,
# extraction decisions, links, and final ledger events remain audited.
_SKIPPED_TYPES = _DOMAIN_AUDITED_TYPES | {
    AuditEvent.__name__,
    "BackgroundJob",
    "DocumentChunk",
    "DocumentPage",
}


def _row_id(value: Any) -> uuid.UUID | None:
    row_id = getattr(value, "id", None)
    if row_id is None and hasattr(value, "id"):
        row_id = uuid.uuid4()
        value.id = row_id
    return row_id if isinstance(row_id, uuid.UUID) else None


def _changed_column_names(value: Any, *, created: bool = False) -> list[str]:
    state = inspect(value)
    names: list[str] = []
    for column in state.mapper.column_attrs:
        name = column.key
        if name in {
            "password_hash",
            "api_key_encrypted",
            "content",
            "text_content",
            "raw_response_json",
            "parsed_rows",
        }:
            continue
        if created or state.attrs[name].history.has_changes():
            names.append(name)
    return sorted(names)


@event.listens_for(Session, "before_flush")
def _collect_automatic_audit(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    context = session.info.get(REQUEST_CONTEXT_INFO_KEY)
    if not isinstance(context, RequestContext):
        return

    pending: list[AuditEvent] = []
    candidates = (
        [(row, "created") for row in session.new]
        + [(row, "updated") for row in session.dirty]
        + [(row, "deleted") for row in session.deleted]
    )
    seen: set[tuple[int, str]] = set()
    for row, verb in candidates:
        marker = (id(row), verb)
        if marker in seen:
            continue
        seen.add(marker)
        if not isinstance(row, FamilyScopedMixin):
            continue
        aggregate_type = type(row).__name__
        if aggregate_type in _SKIPPED_TYPES:
            continue
        family_id = getattr(row, "family_id", None) or context.family_id
        if family_id != context.family_id:
            # family_scope raises the canonical error; do not create an audit
            # event for a write which will be rejected.
            continue
        aggregate_id = _row_id(row)
        if aggregate_id is None:
            continue
        changed_fields = _changed_column_names(row, created=verb == "created")
        if verb == "updated" and not changed_fields:
            continue
        pending.append(
            AuditEvent(
                family_id=context.family_id,
                actor_user_id=(
                    context.user_id
                    if context.user_id.int != 0
                    else None
                ),
                action=f"{aggregate_type.lower()}.{verb}",
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                correlation_id=uuid.uuid4(),
                summary_json={"changed_fields": changed_fields},
            )
        )
    if pending:
        session.add_all(pending)


@event.listens_for(Session, "before_flush")
def _protect_append_only_audit(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    if any(isinstance(row, AuditEvent) for row in session.dirty):
        raise ValueError("audit_event_is_append_only")
    if any(isinstance(row, AuditEvent) for row in session.deleted):
        raise ValueError("audit_event_is_append_only")
