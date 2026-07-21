from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class FXRateSetRequest(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: datetime | None = None


class FXRateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: datetime
    source_provider: str
