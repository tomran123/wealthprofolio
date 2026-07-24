import asyncio
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import monotonic
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Account, Holding, Instrument, PriceSnapshot
from app.models.enums import HoldingSource, PriceSourceType
from app.providers.price.akshare_adapter import AkSharePriceAdapter
from app.providers.price.coingecko_adapter import CoinGeckoPriceAdapter
from app.providers.price.instrument_search import (
    CoinGeckoInstrumentSearchAdapter,
    EastMoneyInstrumentSearchAdapter,
    InstrumentSearchCandidate,
    YahooInstrumentSearchAdapter,
)
from app.providers.price.manual_adapter import ManualPriceAdapter
from app.providers.price.price_router import route_to_adapters
from app.providers.price.yahoo_adapter import YahooPriceAdapter
from app.schemas.holding import MarketHoldingCreateRequest
from app.services import instrument_service, valuation_service

settings = get_settings()
TOKEN_SCOPE = "market-instrument-selection"
TOKEN_TTL_MINUTES = 15
SEARCH_PROVIDER_TIMEOUT_SECONDS = 1.5
SEARCH_CACHE_TTL_SECONDS = 5 * 60
SEARCH_PARTIAL_CACHE_TTL_SECONDS = 30
SEARCH_CACHE_MAX_ENTRIES = 256

SEARCH_ADAPTERS = (
    YahooInstrumentSearchAdapter(),
    EastMoneyInstrumentSearchAdapter(),
    CoinGeckoInstrumentSearchAdapter(),
)


@dataclass(frozen=True, slots=True)
class _ExternalSearchResult:
    source_results: tuple[tuple[InstrumentSearchCandidate, ...], ...]
    unavailable_sources: tuple[str, ...]


_SEARCH_CACHE: OrderedDict[str, tuple[float, _ExternalSearchResult]] = OrderedDict()
_SEARCH_INFLIGHT: dict[str, asyncio.Task[_ExternalSearchResult]] = {}


async def _run_external_search(query: str) -> _ExternalSearchResult:
    async def search_one(adapter: Any) -> tuple[tuple[InstrumentSearchCandidate, ...], bool]:
        try:
            rows = await asyncio.wait_for(
                adapter.search(query),
                timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS,
            )
            return tuple(rows), True
        except Exception:
            return (), False

    results = await asyncio.gather(*(search_one(adapter) for adapter in SEARCH_ADAPTERS))
    return _ExternalSearchResult(
        source_results=tuple(rows for rows, _ in results),
        unavailable_sources=tuple(
            adapter.name
            for adapter, (_, available) in zip(SEARCH_ADAPTERS, results, strict=True)
            if not available
        ),
    )


async def _get_external_search(query: str) -> _ExternalSearchResult:
    cache_key = query.casefold()
    now = monotonic()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached is not None:
        expires_at, result = cached
        if expires_at > now:
            _SEARCH_CACHE.move_to_end(cache_key)
            return result
        _SEARCH_CACHE.pop(cache_key, None)

    task = _SEARCH_INFLIGHT.get(cache_key)
    if task is None:
        task = asyncio.create_task(_run_external_search(query))
        _SEARCH_INFLIGHT[cache_key] = task
    try:
        result = await asyncio.shield(task)
    finally:
        if task.done() and _SEARCH_INFLIGHT.get(cache_key) is task:
            _SEARCH_INFLIGHT.pop(cache_key, None)

    ttl = (
        SEARCH_PARTIAL_CACHE_TTL_SECONDS
        if result.unavailable_sources
        else SEARCH_CACHE_TTL_SECONDS
    )
    _SEARCH_CACHE[cache_key] = (monotonic() + ttl, result)
    _SEARCH_CACHE.move_to_end(cache_key)
    while len(_SEARCH_CACHE) > SEARCH_CACHE_MAX_ENTRIES:
        _SEARCH_CACHE.popitem(last=False)
    return result


def _selection_token(candidate: InstrumentSearchCandidate, instrument_id: uuid.UUID | None = None) -> str:
    payload: dict[str, Any] = {
        "scope": TOKEN_SCOPE,
        "provider": candidate.provider,
        "provider_symbol": candidate.provider_symbol,
        "symbol": candidate.symbol,
        "name": candidate.name,
        "asset_class": candidate.asset_class.value,
        "currency": candidate.currency,
        "market": candidate.market.value,
        "country": candidate.country,
        "exchange": candidate.exchange,
        "external_ids": candidate.external_ids,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    if instrument_id is not None:
        payload["instrument_id"] = str(instrument_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_selection_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("market_selection_expired") from exc
    except jwt.PyJWTError as exc:
        raise ValueError("invalid_market_selection") from exc
    if payload.get("scope") != TOKEN_SCOPE:
        raise ValueError("invalid_market_selection")
    return payload


def _candidate_from_instrument(instrument: Instrument) -> InstrumentSearchCandidate:
    external_ids = {str(key): str(value) for key, value in (instrument.external_ids or {}).items() if value is not None}
    provider = external_ids.get("price_provider") or "local"
    provider_symbol = external_ids.get("provider_symbol") or instrument.symbol or ""
    return InstrumentSearchCandidate(
        provider=provider,
        provider_symbol=provider_symbol,
        symbol=instrument.symbol or instrument.name,
        name=instrument.name,
        asset_class=instrument.asset_class,
        currency=instrument.currency,
        market=instrument.market,
        country=instrument.country,
        external_ids=external_ids,
    )


def _search_item(candidate: InstrumentSearchCandidate, *, instrument_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "selection_token": _selection_token(candidate, instrument_id),
        "symbol": candidate.symbol,
        "name": candidate.name,
        "asset_class": candidate.asset_class,
        "currency": candidate.currency,
        "market": candidate.market,
        "exchange": candidate.exchange,
        "source": "local" if instrument_id is not None else candidate.provider,
        "is_local": instrument_id is not None,
    }


async def search_market_instruments(db: AsyncSession, query: str) -> dict[str, Any]:
    normalized = query.strip()
    if not normalized:
        return {"items": [], "unavailable_sources": []}

    local_rows = await instrument_service.search_instruments(db, normalized)
    local_rows = [row for row in local_rows if row.price_source_type == PriceSourceType.MARKET]
    external_result = await _get_external_search(normalized)

    local_candidates = [(_candidate_from_instrument(row), row.id) for row in local_rows]
    items = [_search_item(candidate, instrument_id=instrument_id) for candidate, instrument_id in local_candidates]
    unavailable_sources = list(external_result.unavailable_sources)
    seen_provider_ids = {
        (candidate.provider, candidate.provider_symbol)
        for candidate, _ in local_candidates
        if candidate.provider != "local" and candidate.provider_symbol
    }
    legacy_local_symbols = {
        (candidate.symbol.upper(), candidate.market.value)
        for candidate, _ in local_candidates
        if candidate.provider == "local"
    }
    for result in external_result.source_results:
        for candidate in result:
            provider_key = (candidate.provider, candidate.provider_symbol)
            symbol_key = (candidate.symbol.upper(), candidate.market.value)
            if provider_key in seen_provider_ids or symbol_key in legacy_local_symbols:
                continue
            seen_provider_ids.add(provider_key)
            items.append(_search_item(candidate))

    query_upper = normalized.upper()
    items.sort(
        key=lambda item: (
            not item["is_local"],
            item["symbol"].upper() != query_upper,
            not item["symbol"].upper().startswith(query_upper),
            not item["name"].lower().startswith(normalized.lower()),
            item["name"],
        )
    )
    return {"items": items[:30], "unavailable_sources": unavailable_sources}


def _candidate_from_payload(payload: dict[str, Any]) -> InstrumentSearchCandidate:
    try:
        from app.models.enums import AssetClass, MarketRegion

        external_ids = {
            str(key): str(value)
            for key, value in dict(payload.get("external_ids") or {}).items()
            if value is not None
        }
        return InstrumentSearchCandidate(
            provider=str(payload["provider"]),
            provider_symbol=str(payload["provider_symbol"]),
            symbol=str(payload["symbol"]),
            name=str(payload["name"]),
            asset_class=AssetClass(str(payload["asset_class"])),
            currency=str(payload["currency"]),
            market=MarketRegion(str(payload["market"])),
            country=str(payload["country"]) if payload.get("country") else None,
            exchange=str(payload["exchange"]) if payload.get("exchange") else None,
            external_ids=external_ids,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid_market_selection") from exc


async def _fetch_quote(candidate: InstrumentSearchCandidate):
    adapter = {
        "akshare": AkSharePriceAdapter(),
        "coingecko": CoinGeckoPriceAdapter(),
        "yahoo": YahooPriceAdapter(),
    }.get(candidate.provider)
    if adapter is None or not candidate.provider_symbol:
        raise ValueError("market_quote_unavailable")
    rows = (
        await adapter.fetch_prices_for_instruments(
            [(candidate.provider_symbol, candidate.asset_class)]
        )
        if isinstance(adapter, AkSharePriceAdapter)
        else await adapter.fetch_prices([candidate.provider_symbol])
    )
    result = next((row for row in rows if row.symbol == candidate.provider_symbol), None)
    if result is None or result.price <= 0:
        raise ValueError("market_quote_unavailable")
    return result


async def _fetch_local_quote(db: AsyncSession, instrument: Instrument):
    groups = route_to_adapters([instrument])
    adapter, routed = next(iter(groups.items()))
    if isinstance(adapter, ManualPriceAdapter) or not routed[0].provider_symbol:
        raise ValueError("market_quote_unavailable")
    try:
        rows = await adapter.fetch_prices([routed[0].provider_symbol])
    except Exception:
        rows = []
    result = next((row for row in rows if row.symbol == routed[0].provider_symbol), None)
    if result is not None and result.price > 0:
        return result, True
    previous = await valuation_service.get_latest_price(db, instrument.id)
    if previous is None or previous.price <= 0:
        raise ValueError("market_quote_unavailable")
    return previous, False


async def _find_existing_instrument(db: AsyncSession, candidate: InstrumentSearchCandidate) -> Instrument | None:
    stmt = select(Instrument).where(
        Instrument.symbol == candidate.symbol,
        Instrument.market == candidate.market,
    )
    rows = list((await db.execute(stmt)).scalars().all())
    for instrument in rows:
        external_ids = instrument.external_ids or {}
        if (
            external_ids.get("price_provider") == candidate.provider
            and external_ids.get("provider_symbol") == candidate.provider_symbol
        ):
            return instrument
    if candidate.provider == "coingecko":
        return None
    return next((row for row in rows if row.price_source_type == PriceSourceType.MARKET), None)


async def add_holding_from_market_search(db: AsyncSession, data: MarketHoldingCreateRequest) -> dict[str, Any]:
    payload = _decode_selection_token(data.selection_token)
    account = await db.get(Account, data.account_id)
    if account is None:
        raise ValueError("account_not_found")

    local_id = payload.get("instrument_id")
    quote_is_new = False
    if local_id:
        try:
            instrument = await db.get(Instrument, uuid.UUID(str(local_id)))
        except ValueError as exc:
            raise ValueError("invalid_market_selection") from exc
        if instrument is None or instrument.price_source_type != PriceSourceType.MARKET:
            raise ValueError("instrument_not_found")
        quote, quote_is_new = await _fetch_local_quote(db, instrument)
    else:
        candidate = _candidate_from_payload(payload)
        quote = await _fetch_quote(candidate)
        instrument = await _find_existing_instrument(db, candidate)
        if instrument is None:
            instrument = Instrument(
                symbol=candidate.symbol,
                name=candidate.name,
                asset_class=candidate.asset_class,
                currency=quote.currency.upper(),
                country=candidate.country,
                market=candidate.market,
                price_source_type=PriceSourceType.MARKET,
                external_ids=candidate.external_ids,
            )
            db.add(instrument)
            await db.flush()
        else:
            instrument.currency = quote.currency.upper()
            instrument.external_ids = {**(instrument.external_ids or {}), **candidate.external_ids}
        quote_is_new = True

    now = datetime.now(timezone.utc)
    try:
        if quote_is_new:
            db.add(
                PriceSnapshot(
                    instrument_id=instrument.id,
                    price=quote.price,
                    currency=quote.currency.upper(),
                    as_of=quote.as_of,
                    fetched_at=now,
                    source_provider=quote.source_provider,
                    quote_status=quote.quote_status,
                )
            )

        holding_stmt = (
            select(Holding)
            .where(Holding.account_id == data.account_id, Holding.instrument_id == instrument.id)
            .with_for_update()
        )
        holding = (await db.execute(holding_stmt)).scalar_one_or_none()
        if holding is None:
            holding = Holding(
                account_id=data.account_id,
                instrument_id=instrument.id,
                quantity=data.quantity,
                source=HoldingSource.MANUAL,
            )
            db.add(holding)
        else:
            holding.quantity = data.quantity
            holding.source = HoldingSource.MANUAL
        await db.commit()
        await db.refresh(holding)
    except Exception:
        await db.rollback()
        raise

    quote_status = quote.quote_status.value if hasattr(quote.quote_status, "value") else str(quote.quote_status)
    return {
        "holding": {
            "id": holding.id,
            "account_id": holding.account_id,
            "instrument_id": holding.instrument_id,
            "quantity": holding.quantity,
            "source": holding.source,
            "instrument_name": instrument.name,
            "instrument_symbol": instrument.symbol,
            "price_source_type": instrument.price_source_type,
        },
        "price": quote.price,
        "currency": quote.currency.upper(),
        "market_value": data.quantity * Decimal(quote.price),
        "quote_status": quote_status,
        "price_as_of": quote.as_of.isoformat(),
        "source_provider": quote.source_provider,
    }