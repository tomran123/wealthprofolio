from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Account, Holding, Instrument
from app.models.enums import AssetClass, PriceSourceType
from app.services import valuation_service

DIMENSIONS = (
    "instrument",
    "account",
    "institution",
    "owner",
    "asset_class",
    "currency",
    "country",
    "exposure_group",
)


class HoldingValuation:
    __slots__ = (
        "holding",
        "value_base",
        "price",
        "price_currency",
        "quote_status",
        "price_as_of",
        "has_price",
        "has_fx",
    )

    def __init__(
        self,
        holding: Holding,
        value_base: Decimal,
        price: Decimal | None,
        price_currency: str | None,
        quote_status: str | None,
        price_as_of: datetime | None,
        has_price: bool,
        has_fx: bool,
    ) -> None:
        self.holding = holding
        self.value_base = value_base
        self.price = price
        self.price_currency = price_currency
        self.quote_status = quote_status
        self.price_as_of = price_as_of
        self.has_price = has_price
        self.has_fx = has_fx


async def _load_holdings(db: AsyncSession) -> list[Holding]:
    stmt = select(Holding).options(
        selectinload(Holding.instrument).selectinload(Instrument.exposure_group),
        selectinload(Holding.account).selectinload(Account.institution),
        selectinload(Holding.account).selectinload(Account.owner),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _resolve_holding_value(db: AsyncSession, holding: Holding, base_currency: str) -> HoldingValuation:
    instrument = holding.instrument
    quantity = holding.quantity

    if instrument.price_source_type in (PriceSourceType.FX_DERIVED, PriceSourceType.FIXED_PRINCIPAL):
        price = Decimal("1")
        price_currency = instrument.currency
        quote_status = "fixed"
        price_as_of = None
        has_price = True
    else:
        snapshot = await valuation_service.get_latest_price(db, instrument.id)
        if snapshot is None:
            return HoldingValuation(holding, Decimal("0"), None, instrument.currency, None, None, False, False)
        price = snapshot.price
        price_currency = snapshot.currency
        quote_status = snapshot.quote_status.value if hasattr(snapshot.quote_status, "value") else str(
            snapshot.quote_status
        )
        price_as_of = snapshot.as_of
        has_price = True

    fx_rate = await valuation_service.get_latest_fx_rate(db, price_currency, base_currency)
    if fx_rate is None:
        return HoldingValuation(holding, Decimal("0"), price, price_currency, quote_status, price_as_of, True, False)

    value_base = quantity * price * fx_rate
    return HoldingValuation(holding, value_base, price, price_currency, quote_status, price_as_of, True, True)


def _dimension_key_label(dimension: str, holding: Holding) -> tuple[str, str]:
    account = holding.account
    instrument = holding.instrument

    if dimension == "instrument":
        return str(instrument.id), instrument.symbol or instrument.name
    if dimension == "account":
        return str(account.id), account.name
    if dimension == "institution":
        inst = account.institution
        return str(inst.id), inst.name
    if dimension == "owner":
        owner = account.owner
        return str(owner.id), owner.name
    if dimension == "asset_class":
        return instrument.asset_class.value, instrument.asset_class.value
    if dimension == "currency":
        return instrument.currency, instrument.currency
    if dimension == "country":
        key = instrument.country or "UNKNOWN"
        return key, key
    if dimension == "exposure_group":
        group = instrument.exposure_group
        if group is None:
            return "UNASSIGNED", "Unclassified / 未分类"
        return str(group.id), group.name
    raise ValueError(f"Unsupported dimension: {dimension}")


def _is_asset(instrument: Instrument) -> bool:
    return instrument.asset_class != AssetClass.LIABILITY


async def aggregate_portfolio(db: AsyncSession, dimension: str, base_currency: str) -> dict:
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unsupported dimension: {dimension}")

    holdings = await _load_holdings(db)
    groups: dict[str, dict] = {}
    total_value = Decimal("0")

    for holding in holdings:
        if holding.quantity == 0:
            continue
        valuation = await _resolve_holding_value(db, holding, base_currency)
        key, label = _dimension_key_label(dimension, holding)
        group = groups.setdefault(
            key,
            {"key": key, "label": label, "value_base": Decimal("0"), "holdings_count": 0, "details": []},
        )
        group["value_base"] += valuation.value_base
        group["holdings_count"] += 1
        group["details"].append(
            {
                "account_id": str(holding.account.id),
                "account_name": holding.account.name,
                "institution_name": holding.account.institution.name,
                "owner_name": holding.account.owner.name,
                "instrument_id": str(holding.instrument.id),
                "instrument_name": holding.instrument.name,
                "instrument_symbol": holding.instrument.symbol,
                "quantity": holding.quantity,
                "price": valuation.price,
                "price_currency": valuation.price_currency,
                "value_base": valuation.value_base,
                "quote_status": valuation.quote_status,
                "price_as_of": valuation.price_as_of.isoformat() if valuation.price_as_of else None,
            }
        )
        if _is_asset(holding.instrument):
            total_value += valuation.value_base

    ordered = sorted(groups.values(), key=lambda g: g["value_base"], reverse=True)
    for group in ordered:
        group["percentage"] = float(group["value_base"] / total_value * 100) if total_value else 0.0

    return {
        "dimension": dimension,
        "base_currency": base_currency,
        "total_value": total_value,
        "groups": ordered,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_portfolio_summary(db: AsyncSession, base_currency: str) -> dict:
    holdings = await _load_holdings(db)
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    missing_price_count = 0
    missing_fx_count = 0
    holdings_count = 0

    for holding in holdings:
        if holding.quantity == 0:
            continue
        holdings_count += 1
        valuation = await _resolve_holding_value(db, holding, base_currency)
        if not valuation.has_price:
            missing_price_count += 1
            continue
        if not valuation.has_fx:
            missing_fx_count += 1
            continue
        if holding.instrument.asset_class == AssetClass.LIABILITY:
            total_liabilities += valuation.value_base
        else:
            total_assets += valuation.value_base

    return {
        "base_currency": base_currency,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": total_assets - total_liabilities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "holdings_count": holdings_count,
        "missing_price_count": missing_price_count,
        "missing_fx_count": missing_fx_count,
    }
