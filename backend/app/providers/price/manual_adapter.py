from app.models import Instrument
from app.providers.price.base import PriceResult


class ManualPriceAdapter:
    name = "manual"

    async def can_handle(self, instrument: Instrument) -> bool:
        return True

    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]:
        # Manual/fixed assets deliberately retain their latest database snapshot.
        return []
