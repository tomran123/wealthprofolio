import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssetClass, MarketRegion, PriceSourceType


class InstrumentBase(BaseModel):
    symbol: str | None = None
    name: str
    asset_class: AssetClass
    currency: str
    country: str | None = None
    market: MarketRegion = MarketRegion.OTHER
    exposure_group_id: uuid.UUID | None = None
    price_source_type: PriceSourceType = PriceSourceType.MANUAL


class InstrumentCreate(InstrumentBase):
    pass


class InstrumentUpdate(BaseModel):
    symbol: str | None = None
    name: str | None = None
    asset_class: AssetClass | None = None
    currency: str | None = None
    country: str | None = None
    market: MarketRegion | None = None
    exposure_group_id: uuid.UUID | None = None
    price_source_type: PriceSourceType | None = None


class InstrumentRead(InstrumentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class MarketInstrumentSearchItem(BaseModel):
    selection_token: str
    symbol: str
    name: str
    asset_class: AssetClass
    currency: str
    market: MarketRegion
    exchange: str | None = None
    source: str
    is_local: bool = False


class MarketInstrumentSearchResponse(BaseModel):
    items: list[MarketInstrumentSearchItem] = Field(default_factory=list)
    unavailable_sources: list[str] = Field(default_factory=list)


class ManualValuationCreate(BaseModel):
    price: Decimal
    currency: str
    as_of: datetime | None = None
    note: str | None = None


class PriceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    price: Decimal
    currency: str
    as_of: datetime
    source_provider: str
    quote_status: str
    note: str | None = None
