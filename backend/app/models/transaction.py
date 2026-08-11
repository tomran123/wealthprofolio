import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FamilyScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TransactionSource, TransactionType

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.instrument import Instrument


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    """An auditable ledger entry whose signed fields describe its holding and cash effects."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("family_id", "idempotency_key", name="uq_transaction_family_idempotency"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, native_enum=False, length=30, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False, default=0)
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    fee_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    linked_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "transactions.id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[TransactionSource] = mapped_column(
        SAEnum(TransactionSource, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TransactionSource.MANUAL,
    )
    is_reversed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "transactions.id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "transactions.id",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )

    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    instrument: Mapped["Instrument | None"] = relationship("Instrument", back_populates="transactions")
    metadata_projection: Mapped["TransactionMetadataProjection | None"] = relationship(
        "TransactionMetadataProjection",
        back_populates="transaction",
        uselist=False,
        primaryjoin=(
            "and_("
            "Transaction.id == TransactionMetadataProjection.transaction_id, "
            "Transaction.family_id == TransactionMetadataProjection.family_id"
            ")"
        ),
        foreign_keys=(
            "[TransactionMetadataProjection.family_id, "
            "TransactionMetadataProjection.transaction_id]"
        ),
    )


class TransactionMetadataProjection(TimestampMixin, FamilyScopedMixin, Base):
    """Effective non-economic fields derived from transaction amendment events."""

    __tablename__ = "transaction_metadata_projections"
    __table_args__ = (
        UniqueConstraint(
            "family_id",
            "transaction_id",
            name="uq_transaction_metadata_projection_family_transaction",
        ),
        ForeignKeyConstraint(
            ["family_id", "transaction_id"],
            ["transactions.family_id", "transactions.id"],
            name="fk_transaction_metadata_projection_transaction_family",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["family_id", "last_event_id"],
            ["transactions.family_id", "transactions.id"],
            name="fk_transaction_metadata_projection_last_event_family",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    transaction: Mapped[Transaction] = relationship(
        "Transaction",
        back_populates="metadata_projection",
        primaryjoin=(
            "and_("
            "TransactionMetadataProjection.transaction_id == Transaction.id, "
            "TransactionMetadataProjection.family_id == Transaction.family_id"
            ")"
        ),
        foreign_keys=(
            "[TransactionMetadataProjection.family_id, "
            "TransactionMetadataProjection.transaction_id]"
        ),
    )
