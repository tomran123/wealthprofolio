from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
    stmt = select(Holding).where(Holding.quantity != 0).options(
        joinedload(Holding.instrument).joinedload(Instrument.exposure_group),
        joinedload(Holding.account).joinedload(Account.institution),
        joinedload(Holding.account).joinedload(Account.owner),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def load_portfolio_valuations(
    db: AsyncSession,
    base_currency: str,
) -> list[HoldingValuation]:
    holdings = await _load_holdings(db)
    snapshots = await valuation_service.get_latest_prices(
        db,
        (holding.instrument_id for holding in holdings),
    )
    price_currencies = {
        (
            holding.instrument.currency
            if holding.instrument.price_source_type
            in (PriceSourceType.FX_DERIVED, PriceSourceType.FIXED_PRINCIPAL)
            else snapshots[holding.instrument_id].currency
        )
        for holding in holdings
        if holding.instrument.price_source_type
        in (PriceSourceType.FX_DERIVED, PriceSourceType.FIXED_PRINCIPAL)
        or holding.instrument_id in snapshots
    }
    fx_rates = await valuation_service.get_latest_fx_rates_for_currencies(
        db,
        price_currencies,
        base_currency,
    )

    valuations: list[HoldingValuation] = []
    for holding in holdings:
        instrument = holding.instrument
        if instrument.price_source_type in (
            PriceSourceType.FX_DERIVED,
            PriceSourceType.FIXED_PRINCIPAL,
        ):
            price = Decimal("1")
            price_currency = instrument.currency.upper()
            quote_status = "fixed"
            price_as_of = None
        else:
            snapshot = snapshots.get(instrument.id)
            if snapshot is None:
                valuations.append(
                    HoldingValuation(
                        holding,
                        Decimal("0"),
                        None,
                        instrument.currency,
                        None,
                        None,
                        False,
                        False,
                    )
                )
                continue
            price = snapshot.price
            price_currency = snapshot.currency.upper()
            quote_status = (
                snapshot.quote_status.value
                if hasattr(snapshot.quote_status, "value")
                else str(snapshot.quote_status)
            )
            price_as_of = snapshot.as_of

        fx_rate = fx_rates.get(price_currency)
        if fx_rate is None:
            valuations.append(
                HoldingValuation(
                    holding,
                    Decimal("0"),
                    price,
                    price_currency,
                    quote_status,
                    price_as_of,
                    True,
                    False,
                )
            )
            continue
        valuations.append(
            HoldingValuation(
                holding,
                holding.quantity * price * fx_rate,
                price,
                price_currency,
                quote_status,
                price_as_of,
                True,
                True,
            )
        )
    return valuations


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


def _is_liability(valuation: HoldingValuation) -> bool:
    """Treat explicit liabilities and every negative market value as debt.

    Cash can legitimately become negative after a purchase.  Its instrument
    remains a cash instrument, so classification must use both the instrument
    type and the signed valuation rather than the asset class alone.
    """

    return (
        valuation.holding.instrument.asset_class == AssetClass.LIABILITY
        or valuation.value_base < 0
    )


def _new_group(key: str, label: str) -> dict:
    return {
        "key": key,
        "label": label,
        "value_base": Decimal("0"),
        "holdings_count": 0,
        "details": [],
    }


def _append_group_valuation(
    groups: dict[str, dict],
    valuation: HoldingValuation,
    dimension: str,
    value_base: Decimal,
) -> None:
    holding = valuation.holding
    key, label = _dimension_key_label(dimension, holding)
    group = groups.setdefault(key, _new_group(key, label))
    group["value_base"] += value_base
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
            "value_base": value_base,
            "quote_status": valuation.quote_status,
            "price_as_of": valuation.price_as_of.isoformat() if valuation.price_as_of else None,
        }
    )


def _finalize_groups(groups: dict[str, dict], total: Decimal) -> list[dict]:
    ordered = sorted(groups.values(), key=lambda group: group["value_base"], reverse=True)
    for group in ordered:
        group["percentage"] = float(group["value_base"] / total * 100) if total else 0.0
    return ordered


def aggregate_valuations(
    valuations: list[HoldingValuation],
    dimension: str,
    base_currency: str,
) -> dict:
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unsupported dimension: {dimension}")

    asset_groups: dict[str, dict] = {}
    liability_groups: dict[str, dict] = {}
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")

    for valuation in valuations:
        # Unknown prices/FX and exact zero values are not meaningful slices.
        # They remain represented by the summary's missing-data counters.
        if not valuation.has_price or not valuation.has_fx or valuation.value_base == 0:
            continue
        if _is_liability(valuation):
            liability_value = abs(valuation.value_base)
            total_liabilities += liability_value
            _append_group_valuation(
                liability_groups,
                valuation,
                dimension,
                liability_value,
            )
        else:
            total_assets += valuation.value_base
            _append_group_valuation(
                asset_groups,
                valuation,
                dimension,
                valuation.value_base,
            )

    return {
        "dimension": dimension,
        "base_currency": base_currency,
        # total_value/groups are retained as the positive-asset view consumed
        # by allocation charts and top-holding lists.
        "total_value": total_assets,
        "groups": _finalize_groups(asset_groups, total_assets),
        "total_liabilities": total_liabilities,
        "liability_groups": _finalize_groups(liability_groups, total_liabilities),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def summarize_valuations(
    valuations: list[HoldingValuation],
    base_currency: str,
) -> dict:
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    missing_price_count = 0
    missing_fx_count = 0
    holdings_count = 0

    for valuation in valuations:
        holdings_count += 1
        if not valuation.has_price:
            missing_price_count += 1
            continue
        if not valuation.has_fx:
            missing_fx_count += 1
            continue
        if valuation.value_base == 0:
            continue
        if _is_liability(valuation):
            total_liabilities += abs(valuation.value_base)
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


async def aggregate_portfolio(db: AsyncSession, dimension: str, base_currency: str) -> dict:
    valuations = await load_portfolio_valuations(db, base_currency)
    return aggregate_valuations(valuations, dimension, base_currency)


async def get_portfolio_summary(db: AsyncSession, base_currency: str) -> dict:
    valuations = await load_portfolio_valuations(db, base_currency)
    return summarize_valuations(valuations, base_currency)
