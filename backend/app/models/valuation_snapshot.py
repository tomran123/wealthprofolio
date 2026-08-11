from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, FamilyScopedMixin, UUIDPrimaryKeyMixin


class ValuationSnapshot(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    """An immutable whole-portfolio valuation captured after a refresh or on demand."""

    __tablename__ = "valuation_snapshots"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_assets: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    total_liabilities: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    net_worth: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    allocation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    refresh_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
