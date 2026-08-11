import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FamilyScopedMixin, UUIDPrimaryKeyMixin


class JournalEntry(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("family_id", "transaction_id", name="uq_journal_entry_family_transaction"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    postings: Mapped[list["JournalPosting"]] = relationship(
        "JournalPosting",
        back_populates="journal_entry",
        cascade="all, delete-orphan",
    )


class JournalPosting(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    __tablename__ = "journal_postings"
    __table_args__ = (
        CheckConstraint("debit >= 0", name="ck_journal_posting_debit_nonnegative"),
        CheckConstraint("credit >= 0", name="ck_journal_posting_credit_nonnegative"),
        CheckConstraint(
            "NOT (debit > 0 AND credit > 0)",
            name="ck_journal_posting_single_side",
        ),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_code: Mapped[str] = mapped_column(String(160), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    journal_entry: Mapped[JournalEntry] = relationship(
        "JournalEntry", back_populates="postings"
    )


class AuditEvent(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    __tablename__ = "audit_events"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class OutboxEvent(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("family_id", "idempotency_key", name="uq_outbox_family_idempotency"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
