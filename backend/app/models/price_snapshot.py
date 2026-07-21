import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import QuoteStatus


class PriceSnapshot(UUIDPrimaryKeyMixin, Base):
    """An immutable point-in-time price observation for an Instrument (market quote,
    manual valuation, or a fixed/derived price for cash & deposits)."""

    __tablename__ = "price_snapshots"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_provider: Mapped[str] = mapped_column(String(60), nullable=False)
    quote_status: Mapped[QuoteStatus] = mapped_column(
        SAEnum(QuoteStatus, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    instrument: Mapped["Instrument"] = relationship("Instrument")
