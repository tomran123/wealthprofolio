import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import HoldingSource, PriceSourceType


class HoldingSetRequest(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal


class HoldingAdjustRequest(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    delta_quantity: Decimal


class HoldingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal
    source: HoldingSource


class HoldingWithInstrument(HoldingRead):
    instrument_name: str
    instrument_symbol: str | None
    price_source_type: PriceSourceType
    price: Decimal | None = None
    price_currency: str | None = None
    market_value: Decimal | None = None
    quote_status: str | None = None
    price_as_of: str | None = None


class MarketHoldingCreateRequest(BaseModel):
    account_id: uuid.UUID
    selection_token: str = Field(min_length=1, max_length=4096)
    quantity: Decimal = Field(gt=0)


class MarketHoldingCreateResult(BaseModel):
    holding: HoldingWithInstrument
    price: Decimal
    currency: str
    market_value: Decimal
    quote_status: str
    price_as_of: str
    source_provider: str
