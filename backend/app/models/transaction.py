import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TransactionSource, TransactionType


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An auditable ledger entry whose signed fields describe its holding and cash effects."""

    __tablename__ = "transactions"

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

    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    instrument: Mapped["Instrument | None"] = relationship("Instrument", back_populates="transactions")
