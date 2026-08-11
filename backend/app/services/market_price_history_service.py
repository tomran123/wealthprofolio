import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MarketRegion, PriceSourceType
from app.providers.price.yahoo_adapter import YahooPriceAdapter
from app.services import instrument_service


async def lookup_historical_market_price(
    db: AsyncSession,
    instrument_id: uuid.UUID,
    as_of: datetime | None,
) -> dict[str, Any]:
    if as_of is None:
        raise ValueError("historical_price_time_required")
    if as_of.tzinfo is None:
        raise ValueError("historical_price_timezone_required")
    instrument = await instrument_service.get_instrument(db, instrument_id)
    if instrument is None:
        raise ValueError("instrument_not_found")
    if instrument.price_source_type != PriceSourceType.MARKET:
        raise ValueError("historical_price_requires_market_instrument")
    if instrument.market not in (MarketRegion.US, MarketRegion.HK):
        raise ValueError("historical_price_provider_unsupported")
    external_ids = instrument.external_ids or {}
    provider = external_ids.get("price_provider")
    if provider not in (None, "local", "yahoo"):
        raise ValueError("historical_price_provider_unsupported")
    symbol = str(external_ids.get("provider_symbol") or instrument.symbol or "").strip()
    if not symbol:
        raise ValueError("instrument_symbol_required")
    result = await YahooPriceAdapter.fetch_historical_price(symbol, as_of)
    if result is None:
        raise ValueError("historical_price_unavailable")
    requested = as_of.astimezone(timezone.utc)
    return {
        "instrument_id": str(instrument.id),
        "symbol": instrument.symbol,
        "requested_as_of": requested.isoformat(),
        "quote_as_of": result.as_of.isoformat(),
        "distance_seconds": int(abs((result.as_of - requested).total_seconds())),
        "price": result.price,
        "currency": result.currency,
        "source_provider": result.source_provider,
        "warning": "nearest_market_quote_not_execution_price",
    }
