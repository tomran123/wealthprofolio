import asyncio
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis_state import redis_delete, redis_get, redis_set
from app.models import Account, Holding, Instrument, PriceSnapshot
from app.models.enums import PriceSourceType
from app.providers.fx import FrankfurterFXAdapter
from app.providers.price.akshare_adapter import AkSharePriceAdapter
from app.providers.price.manual_adapter import ManualPriceAdapter
from app.providers.price.price_router import RoutedInstrument, route_to_adapters
from app.services import settings_service, valuation_service, valuation_snapshot_service

MAX_CONCURRENCY = 10
PRICE_PROVIDER_TIMEOUT_SECONDS = 6.0
FX_PROVIDER_TIMEOUT_SECONDS = 5.0
PROVIDER_FAILURE_BACKOFF_SECONDS = 60.0
PROVIDER_EMPTY_BACKOFF_SECONDS = 30.0
settings = get_settings()
_PROVIDER_BACKOFF_UNTIL: dict[str, float] = {}


def _provider_backoff_key(provider_name: str) -> str:
    return f"wealthportfolio:price-provider-backoff:v1:{provider_name}"


async def _provider_is_backed_off(provider_name: str) -> bool:
    available, value = await redis_get(_provider_backoff_key(provider_name))
    if available:
        _PROVIDER_BACKOFF_UNTIL.pop(provider_name, None)
        return value is not None
    return _PROVIDER_BACKOFF_UNTIL.get(provider_name, 0.0) > monotonic()


async def _set_provider_backoff(provider_name: str, seconds: int) -> None:
    if await redis_set(
        _provider_backoff_key(provider_name),
        "1",
        ttl_seconds=seconds,
    ):
        _PROVIDER_BACKOFF_UNTIL.pop(provider_name, None)
        return
    _PROVIDER_BACKOFF_UNTIL[provider_name] = monotonic() + seconds


async def _clear_provider_backoff(provider_name: str) -> None:
    _PROVIDER_BACKOFF_UNTIL.pop(provider_name, None)
    await redis_delete(_provider_backoff_key(provider_name))


async def load_instruments_needing_refresh(db: AsyncSession) -> list[Instrument]:
    stmt = (
        select(Instrument)
        .join(Holding, Holding.instrument_id == Instrument.id)
        .where(Holding.quantity != 0)
        .distinct()
        .order_by(Instrument.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def collect_portfolio_currencies(db: AsyncSession) -> set[str]:
    instrument_rows = await db.execute(select(distinct(Instrument.currency)))
    account_rows = await db.execute(select(distinct(Account.base_currency)))
    return {
        str(currency).upper()
        for currency in [*instrument_rows.scalars().all(), *account_rows.scalars().all()]
        if currency
    }


async def _fetch_group(
    adapter: Any,
    routed: list[RoutedInstrument],
    semaphore: asyncio.Semaphore,
) -> tuple[list[RoutedInstrument], dict[str, Any], str | None]:
    if await _provider_is_backed_off(adapter.name):
        return routed, {}, f"{adapter.name}: temporarily_unavailable"
    symbols = list(dict.fromkeys(item.provider_symbol for item in routed if item.provider_symbol))
    if not symbols:
        return routed, {}, "missing_symbol"
    try:
        async with semaphore:
            fetch = (
                adapter.fetch_prices_for_instruments(
                    [
                        (item.provider_symbol, item.instrument.asset_class)
                        for item in routed
                        if item.provider_symbol
                    ]
                )
                if isinstance(adapter, AkSharePriceAdapter)
                else adapter.fetch_prices(symbols)
            )
            rows = await asyncio.wait_for(
                fetch,
                timeout=PRICE_PROVIDER_TIMEOUT_SECONDS,
            )
        if not rows:
            await _set_provider_backoff(
                adapter.name,
                int(PROVIDER_EMPTY_BACKOFF_SECONDS),
            )
            return routed, {}, f"{adapter.name}: no_quotes"
        await _clear_provider_backoff(adapter.name)
        return routed, {row.symbol: row for row in rows}, None
    except Exception as exc:
        await _set_provider_backoff(
            adapter.name,
            int(PROVIDER_FAILURE_BACKOFF_SECONDS),
        )
        return routed, {}, f"{adapter.name}: {type(exc).__name__}"


async def _fetch_fx_rates(
    base_currency: str,
    currencies: set[str],
) -> tuple[list[Any], str | None]:
    try:
        rates = await asyncio.wait_for(
            FrankfurterFXAdapter().fetch_rates(base_currency, sorted(currencies)),
            timeout=FX_PROVIDER_TIMEOUT_SECONDS,
        )
        return rates, None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


async def refresh_all_prices(db: AsyncSession, *, commit: bool = True) -> dict[str, Any]:
    instruments = await load_instruments_needing_refresh(db)
    groups = route_to_adapters(instruments)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    now = datetime.now(timezone.utc)
    previous_prices = await valuation_service.get_latest_prices(
        db,
        (instrument.id for instrument in instruments),
    )
    base_currency = await settings_service.get_base_currency(db, settings.default_base_currency)
    currencies = await collect_portfolio_currencies(db)

    success_count = 0
    kept_count = 0
    failed_count = 0
    failed_symbols: list[str] = []
    errors: list[dict[str, str]] = []

    fetch_tasks = [
        _fetch_group(adapter, routed, semaphore)
        for adapter, routed in groups.items()
        if not isinstance(adapter, ManualPriceAdapter)
    ]
    fetched_groups, fx_result = await asyncio.gather(
        asyncio.gather(*fetch_tasks),
        _fetch_fx_rates(base_currency, currencies),
    )
    rates, fx_error = fx_result

    for adapter, routed in groups.items():
        if not isinstance(adapter, ManualPriceAdapter):
            continue
        for item in routed:
            instrument = item.instrument
            if instrument.price_source_type in (PriceSourceType.FX_DERIVED, PriceSourceType.FIXED_PRINCIPAL):
                kept_count += 1
                continue
            previous = previous_prices.get(instrument.id)
            if previous is not None:
                kept_count += 1
            else:
                failed_count += 1
                failed_symbols.append(instrument.symbol or instrument.name)
                errors.append({"symbol": instrument.symbol or instrument.name, "error": "manual_price_missing"})

    for routed, by_symbol, group_error in fetched_groups:
        for item in routed:
            instrument = item.instrument
            result = by_symbol.get(item.provider_symbol)
            display_symbol = instrument.symbol or instrument.name
            if result is not None:
                db.add(
                    PriceSnapshot(
                        instrument_id=instrument.id,
                        price=result.price,
                        currency=result.currency.upper(),
                        as_of=result.as_of,
                        fetched_at=now,
                        source_provider=result.source_provider,
                        quote_status=result.quote_status,
                    )
                )
                success_count += 1
                continue

            previous = previous_prices.get(instrument.id)
            if previous is not None:
                kept_count += 1
            else:
                failed_count += 1
            failed_symbols.append(display_symbol)
            errors.append({"symbol": display_symbol, "error": group_error or "quote_not_returned"})

    for rate in rates:
        db.add(
            valuation_service.build_fx_snapshot(
                rate.base_currency,
                rate.quote_currency,
                rate.rate,
                rate.as_of,
                source_provider=rate.source_provider,
                fetched_at=now,
            )
        )

    if commit:
        await db.commit()
    else:
        await db.flush()
    refresh_result = {
        "success_count": success_count,
        "kept_count": kept_count,
        "failed_count": failed_count,
        "failed_symbols": list(dict.fromkeys(failed_symbols)),
        "errors": errors,
        "fx_error": fx_error,
        "refreshed_at": now.isoformat(),
    }
    snapshot = await valuation_snapshot_service.create_valuation_snapshot(
        db,
        base_currency,
        refresh_result,
        commit=commit,
    )
    refresh_result["snapshot_id"] = str(snapshot.id)
    return refresh_result
