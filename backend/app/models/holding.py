import uuid
from decimal import Decimal

from sqlalchemy import Enum as SAEnum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import HoldingSource


class Holding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The materialized current quantity of one Instrument held in one Account.

    This is intentionally a "current state" table (fast to aggregate/query), separate
    from the append-only Transaction ledger that will be introduced in Phase 3 and will
    keep this table's quantity in sync.
    """

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("account_id", "instrument_id", name="uq_holding_account_instrument"),)

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    source: Mapped[HoldingSource] = mapped_column(
        SAEnum(HoldingSource, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=HoldingSource.MANUAL,
        nullable=False,
    )

    account: Mapped["Account"] = relationship("Account", back_populates="holdings")
    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="holdings")
