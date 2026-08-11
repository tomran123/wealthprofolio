from dataclasses import dataclass

from app.models import Instrument
from app.models.enums import AssetClass, MarketRegion, PriceSourceType
from app.providers.price.akshare_adapter import AkSharePriceAdapter
from app.providers.price.base import PriceProviderAdapter
from app.providers.price.coingecko_adapter import CoinGeckoPriceAdapter
from app.providers.price.manual_adapter import ManualPriceAdapter
from app.providers.price.metals_adapter import MetalsPriceAdapter
from app.providers.price.yahoo_adapter import YahooPriceAdapter

CRYPTO_ID_FALLBACKS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
}


@dataclass(slots=True)
class RoutedInstrument:
    instrument: Instrument
    provider_symbol: str


YAHOO = YahooPriceAdapter()
AKSHARE = AkSharePriceAdapter()
COINGECKO = CoinGeckoPriceAdapter()
METALS = MetalsPriceAdapter()
MANUAL = ManualPriceAdapter()


def _provider_symbol(instrument: Instrument) -> str:
    external_ids = instrument.external_ids or {}
    if instrument.asset_class == AssetClass.CRYPTO:
        return str(
            external_ids.get("coingecko_id")
            or CRYPTO_ID_FALLBACKS.get((instrument.symbol or "").upper())
            or (instrument.symbol or instrument.name).lower()
        )
    return str(external_ids.get("provider_symbol") or instrument.symbol or "")


def choose_adapter(instrument: Instrument) -> PriceProviderAdapter:
    if instrument.price_source_type in (
        PriceSourceType.MANUAL,
        PriceSourceType.FX_DERIVED,
        PriceSourceType.FIXED_PRINCIPAL,
    ):
        return MANUAL
    configured_provider = str((instrument.external_ids or {}).get("price_provider") or "").lower()
    if configured_provider == "yahoo":
        return YAHOO
    if configured_provider == "akshare":
        return AKSHARE
    if configured_provider == "coingecko":
        return COINGECKO
    if configured_provider == "metals":
        return METALS
    if instrument.asset_class == AssetClass.CRYPTO:
        return COINGECKO
    if instrument.asset_class == AssetClass.GOLD:
        return METALS
    if instrument.market == MarketRegion.CN:
        return AKSHARE
    return YAHOO


def route_to_adapters(instruments: list[Instrument]) -> dict[PriceProviderAdapter, list[RoutedInstrument]]:
    groups: dict[PriceProviderAdapter, list[RoutedInstrument]] = {}
    for instrument in instruments:
        adapter = choose_adapter(instrument)
        groups.setdefault(adapter, []).append(
            RoutedInstrument(instrument=instrument, provider_symbol=_provider_symbol(instrument))
        )
    return groups
