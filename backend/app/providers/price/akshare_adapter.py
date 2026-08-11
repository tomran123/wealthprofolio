import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.models import Instrument
from app.models.enums import AssetClass, MarketRegion, QuoteStatus
from app.providers.price.base import PriceResult


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


class AkSharePriceAdapter:
    name = "akshare"

    async def can_handle(self, instrument: Instrument) -> bool:
        return instrument.market == MarketRegion.CN

    @staticmethod
    def _consume_frame(
        frame: object,
        symbols: list[str],
        code_columns: tuple[str, ...],
        price_columns: tuple[str, ...],
        quote_status: QuoteStatus,
    ) -> dict[str, PriceResult]:
        if frame is None or not hasattr(frame, "iterrows"):
            return {}
        columns = set(getattr(frame, "columns", []))
        code_col = next((name for name in code_columns if name in columns), None)
        price_col = next((name for name in price_columns if name in columns), None)
        if not code_col or not price_col:
            return {}

        now = datetime.now(timezone.utc)
        wanted = {
            symbol.lower().removeprefix("sh").removeprefix("sz"): symbol
            for symbol in symbols
        }
        found: dict[str, PriceResult] = {}
        for _, row in frame.iterrows():
            code = str(row[code_col]).strip().lower().removeprefix("sh").removeprefix("sz")
            original = wanted.get(code)
            if not original:
                continue
            price = _decimal(row[price_col])
            if price is None:
                continue
            found[original] = PriceResult(
                symbol=original,
                price=price,
                currency="CNY",
                as_of=now,
                source_provider="akshare",
                quote_status=quote_status,
            )
        return found

    @classmethod
    def _fetch_stock_spot(cls, symbols: list[str]) -> dict[str, PriceResult]:
        import akshare as ak

        try:
            frame = ak.stock_zh_a_spot_em()
        except Exception:
            return {}
        return cls._consume_frame(
            frame,
            symbols,
            ("代码", "symbol"),
            ("最新价", "price"),
            QuoteStatus.DELAYED,
        )

    @classmethod
    def _fetch_etf_spot(cls, symbols: list[str]) -> dict[str, PriceResult]:
        import akshare as ak

        try:
            frame = ak.fund_etf_spot_em()
        except Exception:
            return {}
        return cls._consume_frame(
            frame,
            symbols,
            ("代码", "symbol"),
            ("最新价", "price"),
            QuoteStatus.DELAYED,
        )

    @staticmethod
    def _fetch_open_fund(symbol: str) -> PriceResult | None:
        import akshare as ak

        normalized = symbol.lower().removeprefix("sh").removeprefix("sz")
        try:
            frame = ak.fund_open_fund_info_em(symbol=normalized, indicator="单位净值走势")
            if frame is None or frame.empty:
                return None
            price_col = next((c for c in ("单位净值", "单位净值走势") if c in frame.columns), None)
            if not price_col:
                return None
            price = _decimal(frame.iloc[-1][price_col])
            if price is None:
                return None
            return PriceResult(
                symbol=symbol,
                price=price,
                currency="CNY",
                as_of=datetime.now(timezone.utc),
                source_provider="akshare",
                quote_status=QuoteStatus.CLOSE,
            )
        except Exception:
            return None

    async def fetch_prices_for_instruments(
        self,
        instruments: list[tuple[str, AssetClass | None]],
    ) -> list[PriceResult]:
        requested = dict(instruments)
        if not requested:
            return []

        fallback_symbols = [
            symbol
            for symbol, asset_class in requested.items()
            if asset_class not in (AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUND)
        ]
        stock_symbols = [
            symbol for symbol, asset_class in requested.items() if asset_class == AssetClass.EQUITY
        ] + fallback_symbols
        etf_symbols = [
            symbol for symbol, asset_class in requested.items() if asset_class == AssetClass.ETF
        ] + fallback_symbols

        spot_tasks = []
        if stock_symbols:
            spot_tasks.append(asyncio.to_thread(self._fetch_stock_spot, stock_symbols))
        if etf_symbols:
            spot_tasks.append(asyncio.to_thread(self._fetch_etf_spot, etf_symbols))
        spot_results = await asyncio.gather(*spot_tasks) if spot_tasks else []
        found: dict[str, PriceResult] = {}
        for rows in spot_results:
            found.update(rows)

        open_fund_symbols = [
            symbol for symbol, asset_class in requested.items() if asset_class == AssetClass.FUND
        ] + [symbol for symbol in fallback_symbols if symbol not in found]
        semaphore = asyncio.Semaphore(4)

        async def fetch_open_fund(symbol: str) -> PriceResult | None:
            async with semaphore:
                return await asyncio.to_thread(self._fetch_open_fund, symbol)

        fund_rows = await asyncio.gather(*(fetch_open_fund(symbol) for symbol in open_fund_symbols))
        for row in fund_rows:
            if row is not None:
                found[row.symbol] = row

        return [found[symbol] for symbol in requested if symbol in found]

    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]:
        return await self.fetch_prices_for_instruments([(symbol, None) for symbol in symbols])
