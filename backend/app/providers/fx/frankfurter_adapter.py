from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import BaseModel


class FXResult(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: datetime
    source_provider: str = "frankfurter"


class FrankfurterFXAdapter:
    """Frankfurter v2 client. Its public API is keyless and returns one row per pair."""

    base_url = "https://api.frankfurter.dev/v2"

    async def fetch_rates(self, base_currency: str, quote_currencies: list[str]) -> list[FXResult]:
        base = base_currency.upper()
        quotes = sorted({currency.upper() for currency in quote_currencies if currency.upper() != base})
        if not quotes:
            return []
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self.base_url}/rates",
                params={"base": base, "quotes": ",".join(quotes)},
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

        results: list[FXResult] = []
        for row in payload if isinstance(payload, list) else []:
            try:
                rate = Decimal(str(row["rate"]))
                row_date = date.fromisoformat(str(row["date"]))
                quote = str(row["quote"]).upper()
            except (KeyError, InvalidOperation, TypeError, ValueError):
                continue
            results.append(
                FXResult(
                    base_currency=str(row.get("base") or base).upper(),
                    quote_currency=quote,
                    rate=rate,
                    as_of=datetime.combine(row_date, time.min, tzinfo=timezone.utc),
                )
            )
        return results
