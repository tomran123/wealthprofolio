import asyncio
from dataclasses import dataclass, field

import httpx

from app.models.enums import AssetClass, MarketRegion


@dataclass(frozen=True, slots=True)
class InstrumentSearchCandidate:
    provider: str
    provider_symbol: str
    symbol: str
    name: str
    asset_class: AssetClass
    currency: str
    market: MarketRegion
    country: str | None = None
    exchange: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)


def _country_for_market(market: MarketRegion) -> str | None:
    return {
        MarketRegion.US: "US",
        MarketRegion.HK: "HK",
        MarketRegion.CN: "CN",
    }.get(market)


def _yahoo_market(symbol: str, exchange: str) -> MarketRegion:
    upper_symbol = symbol.upper()
    upper_exchange = exchange.upper()
    if upper_symbol.endswith(".HK") or upper_exchange in {"HKG", "HKS"}:
        return MarketRegion.HK
    if upper_symbol.endswith((".SS", ".SZ", ".BJ")) or upper_exchange in {"SHH", "SHZ", "BJS"}:
        return MarketRegion.CN
    if upper_exchange in {
        "ASE",
        "BTS",
        "NAS",
        "NCM",
        "NGM",
        "NMS",
        "NYQ",
        "PCX",
        "PNK",
    }:
        return MarketRegion.US
    return MarketRegion.OTHER


YAHOO_ASSET_CLASSES = {
    "BOND": AssetClass.BOND,
    "CRYPTOCURRENCY": AssetClass.CRYPTO,
    "EQUITY": AssetClass.EQUITY,
    "ETF": AssetClass.ETF,
    "FUTURE": AssetClass.CUSTOM,
    "MONEYMARKET": AssetClass.FUND,
    "MUTUALFUND": AssetClass.FUND,
}


class YahooInstrumentSearchAdapter:
    name = "yahoo"
    base_url = "https://query2.finance.yahoo.com/v1/finance/search"

    @staticmethod
    def _search_with_yfinance(query: str, limit: int) -> list[dict]:
        import yfinance as yf

        search = yf.Search(
            query,
            max_results=limit,
            news_count=0,
            lists_count=0,
            include_cb=False,
            enable_fuzzy_query=True,
            timeout=4,
            raise_errors=True,
        )
        return list(search.quotes)

    async def search(self, query: str, limit: int = 12) -> list[InstrumentSearchCandidate]:
        rows: list[dict]
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(
                    self.base_url,
                    params={
                        "q": query,
                        "quotesCount": limit,
                        "newsCount": 0,
                        "listsCount": 0,
                        "enableFuzzyQuery": "true",
                    },
                    headers={"accept": "application/json", "user-agent": "Mozilla/5.0 WealthPortfolio/1.0"},
                )
                response.raise_for_status()
                rows = list(response.json().get("quotes") or [])
        except Exception:
            rows = await asyncio.to_thread(self._search_with_yfinance, query, limit)

        results: list[InstrumentSearchCandidate] = []
        for row in rows:
            quote_type = str(row.get("quoteType") or "").upper()
            asset_class = YAHOO_ASSET_CLASSES.get(quote_type)
            symbol = str(row.get("symbol") or "").strip()
            if asset_class is None or not symbol or len(symbol) > 30:
                continue
            exchange = str(row.get("exchange") or row.get("exchDisp") or "").strip()
            market = MarketRegion.CRYPTO if asset_class == AssetClass.CRYPTO else _yahoo_market(symbol, exchange)
            currency = str(row.get("currency") or "").upper()
            if len(currency) != 3:
                currency = {
                    MarketRegion.CN: "CNY",
                    MarketRegion.HK: "HKD",
                }.get(market, "USD")
            name = str(row.get("longname") or row.get("shortname") or symbol).strip()[:200]
            results.append(
                InstrumentSearchCandidate(
                    provider=self.name,
                    provider_symbol=symbol,
                    symbol=symbol,
                    name=name,
                    asset_class=asset_class,
                    currency=currency,
                    market=market,
                    country=_country_for_market(market),
                    exchange=exchange or None,
                    external_ids={"price_provider": self.name, "provider_symbol": symbol},
                )
            )
        return results


class EastMoneyInstrumentSearchAdapter:
    """Keyless EastMoney suggestion endpoint for mainland securities and funds."""

    name = "akshare"
    base_url = "https://searchapi.eastmoney.com/api/suggest/get"

    @staticmethod
    def _asset_class(row: dict) -> AssetClass | None:
        classify = str(row.get("Classify") or "").lower()
        security_name = str(row.get("SecurityTypeName") or "").lower()
        if not (
            "astock" in classify
            or "fund" in classify
            or "a股" in security_name
            or "基金" in security_name
        ):
            return None
        description = " ".join(
            str(row.get(key) or "")
            for key in ("Classify", "SecurityTypeName", "SecurityType", "Name")
        ).lower()
        if "etf" in description:
            return AssetClass.ETF
        if "fund" in description or "基金" in description:
            return AssetClass.FUND
        if "bond" in description or "债" in description:
            return AssetClass.BOND
        if "stock" in description or "股" in description or "astock" in description:
            return AssetClass.EQUITY
        return None

    async def search(self, query: str, limit: int = 12) -> list[InstrumentSearchCandidate]:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                self.base_url,
                params={
                    "input": query,
                    "type": 14,
                    "token": "D43BF722C8E33BDC906FB84D85E326E8",
                    "count": limit,
                },
                headers={"accept": "application/json", "user-agent": "Mozilla/5.0 WealthPortfolio/1.0"},
            )
            response.raise_for_status()
            payload = response.json()

        table = payload.get("QuotationCodeTable") or {}
        rows = table.get("Data") or payload.get("Data") or []
        results: list[InstrumentSearchCandidate] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("Code") or "").strip()
            name = str(row.get("Name") or code).strip()[:200]
            asset_class = self._asset_class(row)
            if not code or len(code) > 30 or asset_class is None:
                continue
            quote_id = str(row.get("QuoteID") or row.get("ID") or "").strip()
            external_ids = {"price_provider": self.name, "provider_symbol": code}
            if quote_id:
                external_ids["eastmoney_quote_id"] = quote_id
            results.append(
                InstrumentSearchCandidate(
                    provider=self.name,
                    provider_symbol=code,
                    symbol=code,
                    name=name,
                    asset_class=asset_class,
                    currency="CNY",
                    market=MarketRegion.CN,
                    country="CN",
                    exchange=str(row.get("JYS") or row.get("MarketType") or "").strip() or None,
                    external_ids=external_ids,
                )
            )
        return results


class CoinGeckoInstrumentSearchAdapter:
    name = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"

    async def search(self, query: str, limit: int = 10) -> list[InstrumentSearchCandidate]:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                f"{self.base_url}/search",
                params={"query": query},
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

        results: list[InstrumentSearchCandidate] = []
        for row in (payload.get("coins") or [])[:limit]:
            coin_id = str(row.get("id") or "").strip()
            symbol = str(row.get("symbol") or "").upper().strip()
            if not coin_id or not symbol or len(symbol) > 30:
                continue
            results.append(
                InstrumentSearchCandidate(
                    provider=self.name,
                    provider_symbol=coin_id,
                    symbol=symbol,
                    name=str(row.get("name") or symbol).strip()[:200],
                    asset_class=AssetClass.CRYPTO,
                    currency="USD",
                    market=MarketRegion.CRYPTO,
                    external_ids={
                        "price_provider": self.name,
                        "provider_symbol": coin_id,
                        "coingecko_id": coin_id,
                    },
                )
            )
        return results