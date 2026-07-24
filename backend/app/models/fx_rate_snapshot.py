from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class FXRateSnapshot(UUIDPrimaryKeyMixin, Base):
    """An immutable point-in-time exchange rate observation: 1 base_currency = rate quote_currency."""

    __tablename__ = "fx_rate_snapshots"
    __table_args__ = (
        Index(
            "ix_fx_rate_snapshots_pair_as_of",
            "base_currency",
            "quote_currency",
            "as_of",
            "fetched_at",
        ),
    )

    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_provider: Mapped[str] = mapped_column(String(60), nullable=False)
