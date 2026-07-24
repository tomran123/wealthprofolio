from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.models import Instrument
from app.models.enums import AssetClass, QuoteStatus
from app.providers.price.base import PriceResult


class CoinGeckoPriceAdapter:
    name = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"

    async def can_handle(self, instrument: Instrument) -> bool:
        return instrument.asset_class == AssetClass.CRYPTO

    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]:
        if not symbols:
            return []
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self.base_url}/simple/price",
                params={
                    "ids": ",".join(symbols),
                    "vs_currencies": "usd",
                    "include_last_updated_at": "true",
                    "precision": "full",
                },
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

        results: list[PriceResult] = []
        now = datetime.now(timezone.utc)
        for symbol in symbols:
            row = payload.get(symbol, {})
            try:
                price = Decimal(str(row["usd"]))
            except (KeyError, InvalidOperation, TypeError, ValueError):
                continue
            timestamp = row.get("last_updated_at")
            as_of = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else now
            results.append(
                PriceResult(
                    symbol=symbol,
                    price=price,
                    currency="USD",
                    as_of=as_of,
                    source_provider="coingecko",
                    quote_status=QuoteStatus.REALTIME,
                )
            )
        return results
