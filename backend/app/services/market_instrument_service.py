import asyncio
import hashlib
import json
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import monotonic
from typing import Any

import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.family_scope import family_scoped_get, require_bound_family_id
from app.core.redis_state import redis_get, redis_set
from app.models import Account, Holding, Instrument, PriceSnapshot
from app.models.enums import (
    AssetClass,
    MarketRegion,
    PriceSourceType,
    TransactionSource,
)
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
from app.services import instrument_service, transaction_service, valuation_service

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


def _search_cache_key(query: str) -> str:
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
    return f"wealthportfolio:market-search:v1:{digest}"


def _serialize_external_search(result: _ExternalSearchResult) -> str:
    return json.dumps(
        {
            "source_results": [
                [
                    {
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
                    }
                    for candidate in source
                ]
                for source in result.source_results
            ],
            "unavailable_sources": list(result.unavailable_sources),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _deserialize_external_search(value: str) -> _ExternalSearchResult:
    payload = json.loads(value)
    return _ExternalSearchResult(
        source_results=tuple(
            tuple(
                InstrumentSearchCandidate(
                    provider=str(candidate["provider"]),
                    provider_symbol=str(candidate["provider_symbol"]),
                    symbol=str(candidate["symbol"]),
                    name=str(candidate["name"]),
                    asset_class=AssetClass(str(candidate["asset_class"])),
                    currency=str(candidate["currency"]),
                    market=MarketRegion(str(candidate["market"])),
                    country=(
                        str(candidate["country"])
                        if candidate.get("country")
                        else None
                    ),
                    exchange=(
                        str(candidate["exchange"])
                        if candidate.get("exchange")
                        else None
                    ),
                    external_ids={
                        str(key): str(item)
                        for key, item in dict(
                            candidate.get("external_ids") or {}
                        ).items()
                    },
                )
                for candidate in source
            )
            for source in payload["source_results"]
        ),
        unavailable_sources=tuple(
            str(source) for source in payload["unavailable_sources"]
        ),
    )


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
    distributed_key = _search_cache_key(query)
    redis_available, distributed_value = await redis_get(distributed_key)
    if distributed_value is not None:
        try:
            return _deserialize_external_search(distributed_value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            # A schema/version mismatch is a miss. The versioned key prevents
            # this in normal releases, while keeping corrupt cache data inert.
            pass

    now = monotonic()
    if not redis_available:
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
    stored_distributed = await redis_set(
        distributed_key,
        _serialize_external_search(result),
        ttl_seconds=ttl,
    )
    if not stored_distributed:
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


def _market_holding_result(
    data: MarketHoldingCreateRequest,
    holding: Holding,
    instrument: Instrument,
    quote: Any,
) -> dict[str, Any]:
    quote_status = (
        quote.quote_status.value
        if hasattr(quote.quote_status, "value")
        else str(quote.quote_status)
    )
    return {
        "holding": {
            "id": holding.id,
            "account_id": holding.account_id,
            "instrument_id": holding.instrument_id,
            "quantity": holding.quantity,
            "source": holding.source,
            "projection_version": holding.projection_version,
            "last_event_id": holding.last_event_id,
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


async def add_holding_from_market_search(
    db: AsyncSession,
    data: MarketHoldingCreateRequest,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    fingerprint = transaction_service._command_fingerprint(
        "market_holding",
        data.model_dump(mode="json"),
    )
    existing = await transaction_service._existing_transaction(
        db,
        idempotency_key,
        fingerprint,
    )
    if existing is not None:
        if existing.instrument_id is None:
            raise RuntimeError("idempotent_market_holding_instrument_missing")
        instrument = await family_scoped_get(db, Instrument, existing.instrument_id)
        holding = (
            await db.execute(
                select(Holding).where(
                    Holding.account_id == existing.account_id,
                    Holding.instrument_id == existing.instrument_id,
                )
            )
        ).scalar_one_or_none()
        quote = await valuation_service.get_latest_price(db, existing.instrument_id)
        if instrument is None or holding is None or quote is None:
            raise RuntimeError("idempotent_market_holding_projection_missing")
        return _market_holding_result(data, holding, instrument, quote)

    payload = _decode_selection_token(data.selection_token)
    account = await family_scoped_get(db, Account, data.account_id)
    if account is None:
        raise ValueError("account_not_found")

    local_id = payload.get("instrument_id")
    quote_is_new = False
    if local_id:
        try:
            instrument = await family_scoped_get(
                db, Instrument, uuid.UUID(str(local_id))
            )
        except ValueError as exc:
            raise ValueError("invalid_market_selection") from exc
        if instrument is None or instrument.price_source_type != PriceSourceType.MARKET:
            raise ValueError("instrument_not_found")
        quote, quote_is_new = await _fetch_local_quote(db, instrument)
    else:
        candidate = _candidate_from_payload(payload)
        quote = await _fetch_quote(candidate)
        family_id = require_bound_family_id(db)
        instrument_identity = (
            f"{family_id}:{candidate.provider}:{candidate.provider_symbol}:"
            f"{candidate.symbol}:{candidate.market.value}"
        )
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(
                        f"market-instrument:{instrument_identity}",
                        0,
                    )
                )
            )
        )
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

        holding = (
            await db.execute(
                select(Holding)
                .where(
                    Holding.account_id == data.account_id,
                    Holding.instrument_id == instrument.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if holding is None:
            await transaction_service.create_opening_balance(
                db,
                data.account_id,
                instrument.id,
                data.quantity,
                quote.currency,
                TransactionSource.MANUAL,
                commit=False,
                idempotency_key=idempotency_key,
                idempotency_fingerprint_override=fingerprint,
                metadata={"origin": "market_search"},
            )
        else:
            await transaction_service.create_reconciliation_transaction(
                db,
                data.account_id,
                instrument.id,
                quote.currency,
                TransactionSource.MANUAL,
                target_quantity=data.quantity,
                commit=False,
                idempotency_key=idempotency_key,
                idempotency_fingerprint_override=fingerprint,
                metadata={"origin": "market_search"},
            )
        await db.commit()
        holding = (
            await db.execute(
                select(Holding).where(
                    Holding.account_id == data.account_id,
                    Holding.instrument_id == instrument.id,
                )
            )
        ).scalar_one()
    except Exception:
        await db.rollback()
        raise

    return _market_holding_result(data, holding, instrument, quote)
