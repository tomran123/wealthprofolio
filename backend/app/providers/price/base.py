from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel

from app.models import Instrument
from app.models.enums import QuoteStatus


class PriceResult(BaseModel):
    symbol: str
    price: Decimal
    currency: str
    as_of: datetime
    source_provider: str
    quote_status: QuoteStatus


class PriceProviderAdapter(Protocol):
    name: str

    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]: ...

    async def can_handle(self, instrument: Instrument) -> bool: ...
