"""Pure service-level checks for positive assets and liability classification."""

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.models.enums import AssetClass
from app.services.portfolio_service import (
    HoldingValuation,
    aggregate_valuations,
    summarize_valuations,
)


def _valuation(
    *,
    symbol: str,
    asset_class: AssetClass,
    quantity: str,
    value_base: str,
    has_price: bool = True,
    has_fx: bool = True,
) -> HoldingValuation:
    instrument = SimpleNamespace(
        id=uuid.uuid4(),
        name=symbol,
        symbol=symbol,
        asset_class=asset_class,
        currency="USD",
        country="US",
        exposure_group=None,
    )
    account = SimpleNamespace(
        id=uuid.uuid4(),
        name="Test Account",
        institution=SimpleNamespace(id=uuid.uuid4(), name="Test Institution"),
        owner=SimpleNamespace(id=uuid.uuid4(), name="Test Owner"),
    )
    holding = SimpleNamespace(
        instrument=instrument,
        account=account,
        quantity=Decimal(quantity),
    )
    return HoldingValuation(
        holding=holding,
        value_base=Decimal(value_base),
        price=Decimal("1") if has_price else None,
        price_currency="USD",
        quote_status="fixed" if has_price else None,
        price_as_of=None,
        has_price=has_price,
        has_fx=has_fx,
    )


def main() -> None:
    positive_etf = _valuation(
        symbol="SPY",
        asset_class=AssetClass.ETF,
        quantity="800",
        value_base="548000",
    )
    positive_cash = _valuation(
        symbol="USD",
        asset_class=AssetClass.CASH,
        quantity="1000",
        value_base="1000",
    )
    negative_cash = _valuation(
        symbol="USD",
        asset_class=AssetClass.CASH,
        quantity="-548000",
        value_base="-548000",
    )
    explicit_liability = _valuation(
        symbol="MORTGAGE",
        asset_class=AssetClass.LIABILITY,
        quantity="250000",
        value_base="250000",
    )
    missing_price = _valuation(
        symbol="UNKNOWN",
        asset_class=AssetClass.CUSTOM,
        quantity="1",
        value_base="0",
        has_price=False,
        has_fx=False,
    )
    valuations = [
        positive_etf,
        positive_cash,
        negative_cash,
        explicit_liability,
        missing_price,
    ]

    # Regression for the reported purchase: the acquired security is the only
    # allocation slice, while the negative cash balance is debt of equal size.
    purchase_summary = summarize_valuations([positive_etf, negative_cash], "USD")
    purchase_aggregate = aggregate_valuations(
        [positive_etf, negative_cash],
        "instrument",
        "USD",
    )
    assert purchase_summary["total_assets"] == Decimal("548000")
    assert purchase_summary["total_liabilities"] == Decimal("548000")
    assert purchase_summary["net_worth"] == Decimal("0")
    assert len(purchase_aggregate["groups"]) == 1
    assert purchase_aggregate["groups"][0]["label"] == "SPY"
    assert purchase_aggregate["groups"][0]["percentage"] == 100.0
    assert purchase_aggregate["liability_groups"][0]["label"] == "USD"

    summary = summarize_valuations(valuations, "USD")
    assert summary["total_assets"] == Decimal("549000")
    assert summary["total_liabilities"] == Decimal("798000")
    assert summary["net_worth"] == Decimal("-249000")
    assert summary["missing_price_count"] == 1

    aggregate = aggregate_valuations(valuations, "asset_class", "USD")
    assert aggregate["total_value"] == Decimal("549000")
    assert aggregate["total_liabilities"] == Decimal("798000")
    assert {group["key"] for group in aggregate["groups"]} == {"etf", "cash"}
    assert {group["key"] for group in aggregate["liability_groups"]} == {
        "cash",
        "liability",
    }
    assert all(group["value_base"] > 0 for group in aggregate["groups"])
    assert all(group["value_base"] > 0 for group in aggregate["liability_groups"])
    assert abs(sum(group["percentage"] for group in aggregate["groups"]) - 100) < 1e-9
    assert (
        abs(
            sum(group["percentage"] for group in aggregate["liability_groups"])
            - 100
        )
        < 1e-9
    )
    assert all(
        detail["value_base"] > 0
        for group in aggregate["groups"]
        for detail in group["details"]
    )
    assert all(
        detail["value_base"] > 0
        for group in aggregate["liability_groups"]
        for detail in group["details"]
    )

    instrument_aggregate = aggregate_valuations(valuations, "instrument", "USD")
    assert [group["label"] for group in instrument_aggregate["groups"]] == [
        "SPY",
        "USD",
    ]
    assert [group["label"] for group in instrument_aggregate["liability_groups"]] == [
        "USD",
        "MORTGAGE",
    ]
    print("portfolio_aggregation_ok assets=549000 liabilities=798000 net=-249000")


if __name__ == "__main__":
    main()
