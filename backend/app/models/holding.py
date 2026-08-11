import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FamilyScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import HoldingSource

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.instrument import Instrument


class Holding(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    """The materialized current quantity of one Instrument held in one Account.

    This is intentionally a current-state projection for fast reads. Only the
    transaction event service and deterministic replay may write its quantity.
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
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )

    account: Mapped["Account"] = relationship("Account", back_populates="holdings")
    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="holdings")
