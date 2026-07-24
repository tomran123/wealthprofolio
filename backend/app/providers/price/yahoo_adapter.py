import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote

import httpx

from app.models import Instrument
from app.models.enums import MarketRegion, QuoteStatus
from app.providers.price.base import PriceResult


class YahooPriceAdapter:
    name = "yahoo"

    async def can_handle(self, instrument: Instrument) -> bool:
        return instrument.market in (MarketRegion.US, MarketRegion.HK)

    @staticmethod
    def _fetch_one(symbol: str) -> PriceResult | None:
        # yfinance is deliberately imported lazily so a missing optional market-data
        # dependency does not prevent manual portfolios from starting.
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        history = ticker.history(
            period="5d",
            interval="1d",
            auto_adjust=False,
            actions=False,
            timeout=4,
        )
        if history.empty:
            return None

        valid = history.dropna(subset=["Close"])
        if valid.empty:
            return None

        last_index = valid.index[-1]
        last_row = valid.iloc[-1]
        price = Decimal(str(last_row["Close"]))

        if hasattr(last_index, "to_pydatetime"):
            as_of = last_index.to_pydatetime()
        elif isinstance(last_index, datetime):
            as_of = last_index
        else:
            as_of = datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        else:
            as_of = as_of.astimezone(timezone.utc)

        metadata = getattr(ticker, "history_metadata", {}) or {}
        currency = str(metadata.get("currency") or "USD").upper()
        age_seconds = max(0.0, (datetime.now(timezone.utc) - as_of).total_seconds())
        status = QuoteStatus.CLOSE if age_seconds > 24 * 60 * 60 else QuoteStatus.DELAYED
        return PriceResult(
            symbol=symbol,
            price=price,
            currency=currency,
            as_of=as_of,
            source_provider="yahoo",
            quote_status=status,
        )

    @staticmethod
    async def _fetch_direct(symbol: str) -> PriceResult | None:
        """Fallback to Yahoo's chart v8 JSON when yfinance is temporarily throttled."""
        encoded_symbol = quote(symbol, safe="")
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}",
                params={"range": "5d", "interval": "1d"},
                headers={"accept": "application/json", "user-agent": "Mozilla/5.0 WealthPortfolio/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("chart", {}).get("result") or []
        if not rows:
            return None
        row = rows[0]
        meta = row.get("meta") or {}
        timestamp = meta.get("regularMarketTime")
        raw_price = meta.get("regularMarketPrice")
        if raw_price is None:
            timestamps = row.get("timestamp") or []
            closes = (((row.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
            valid = [(ts, close) for ts, close in zip(timestamps, closes, strict=False) if close is not None]
            if not valid:
                return None
            timestamp, raw_price = valid[-1]
        as_of = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
        age_seconds = max(0.0, (datetime.now(timezone.utc) - as_of).total_seconds())
        return PriceResult(
            symbol=symbol,
            price=Decimal(str(raw_price)),
            currency=str(meta.get("currency") or "USD").upper(),
            as_of=as_of,
            source_provider="yahoo_v8",
            quote_status=QuoteStatus.CLOSE if age_seconds > 24 * 60 * 60 else QuoteStatus.DELAYED,
        )

    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]:
        semaphore = asyncio.Semaphore(10)

        async def fetch(symbol: str) -> PriceResult | None:
            async with semaphore:
                try:
                    row = await asyncio.to_thread(self._fetch_one, symbol)
                except Exception:
                    row = None
                if row is not None:
                    return row
                try:
                    return await self._fetch_direct(symbol)
                except Exception:
                    return None

        rows = await asyncio.gather(*(fetch(symbol) for symbol in symbols))
        return [row for row in rows if row is not None]

    @staticmethod
    async def fetch_historical_price(symbol: str, as_of: datetime) -> PriceResult | None:
        """Return the nearest five-minute close around a timezone-aware timestamp."""
        if as_of.tzinfo is None:
            raise ValueError("historical_price_timezone_required")
        requested = as_of.astimezone(timezone.utc)
        start = requested - timedelta(days=1)
        end = requested + timedelta(days=1)
        encoded_symbol = quote(symbol, safe="")
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}",
                params={
                    "period1": int(start.timestamp()),
                    "period2": int(end.timestamp()),
                    "interval": "5m",
                    "events": "history",
                },
                headers={
                    "accept": "application/json",
                    "user-agent": "Mozilla/5.0 WealthPortfolio/1.0",
                },
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("chart", {}).get("result") or []
        if not rows:
            return None
        row = rows[0]
        timestamps = row.get("timestamp") or []
        closes = (((row.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
        candidates = [
            (datetime.fromtimestamp(timestamp, tz=timezone.utc), close)
            for timestamp, close in zip(timestamps, closes, strict=False)
            if close is not None
        ]
        if not candidates:
            return None
        quote_time, raw_price = min(
            candidates,
            key=lambda item: abs((item[0] - requested).total_seconds()),
        )
        metadata = row.get("meta") or {}
        return PriceResult(
            symbol=symbol,
            price=Decimal(str(raw_price)),
            currency=str(metadata.get("currency") or "USD").upper(),
            as_of=quote_time,
            source_provider="yahoo_v8_5m",
            quote_status=QuoteStatus.CLOSE,
        )
