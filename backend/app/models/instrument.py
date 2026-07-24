import uuid

from sqlalchemy import Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AssetClass, MarketRegion, PriceSourceType


class Instrument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A unified asset product (a stock, ETF, fund, cash currency, real estate, etc.)
    that can be held across many accounts. This is the entity cross-account aggregation
    groups by."""

    __tablename__ = "instruments"

    symbol: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        SAEnum(AssetClass, native_enum=False, length=30, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    market: Mapped[MarketRegion] = mapped_column(
        SAEnum(MarketRegion, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=MarketRegion.OTHER,
        nullable=False,
    )
    exposure_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exposure_groups.id", ondelete="SET NULL"), nullable=True
    )
    price_source_type: Mapped[PriceSourceType] = mapped_column(
        SAEnum(PriceSourceType, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=PriceSourceType.MANUAL,
        nullable=False,
    )
    external_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    exposure_group: Mapped["ExposureGroup | None"] = relationship("ExposureGroup", back_populates="instruments")
    holdings: Mapped[list["Holding"]] = relationship("Holding", back_populates="instrument")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="instrument")
