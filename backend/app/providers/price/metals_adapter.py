from app.models import Instrument
from app.models.enums import AssetClass
from app.providers.price.base import PriceResult
from app.providers.price.yahoo_adapter import YahooPriceAdapter


METAL_YAHOO_SYMBOLS = {
    "XAU": "GC=F",
    "GOLD": "GC=F",
    "XAG": "SI=F",
    "SILVER": "SI=F",
    "XPT": "PL=F",
    "PLATINUM": "PL=F",
    "XPD": "PA=F",
    "PALLADIUM": "PA=F",
}


class MetalsPriceAdapter:
    name = "metals"

    def __init__(self) -> None:
        self.yahoo = YahooPriceAdapter()

    async def can_handle(self, instrument: Instrument) -> bool:
        return instrument.asset_class == AssetClass.GOLD

    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]:
        mapped = {symbol: METAL_YAHOO_SYMBOLS.get(symbol.upper(), symbol) for symbol in symbols}
        rows = await self.yahoo.fetch_prices(list(dict.fromkeys(mapped.values())))
        by_provider_symbol = {row.symbol: row for row in rows}
        results: list[PriceResult] = []
        for original, provider_symbol in mapped.items():
            row = by_provider_symbol.get(provider_symbol)
            if row is not None:
                results.append(
                    row.model_copy(update={"symbol": original, "source_provider": "yahoo_metals_proxy"})
                )
        return results
