from decimal import Decimal

from pydantic import BaseModel


class HoldingDetail(BaseModel):
    account_id: str
    account_name: str
    institution_name: str
    owner_name: str
    instrument_id: str
    instrument_name: str
    instrument_symbol: str | None
    quantity: Decimal
    price: Decimal | None
    price_currency: str | None
    value_base: Decimal
    quote_status: str | None
    price_as_of: str | None


class AggregateGroup(BaseModel):
    key: str
    label: str
    value_base: Decimal
    percentage: float
    holdings_count: int
    details: list[HoldingDetail]


class AggregateResponse(BaseModel):
    dimension: str
    base_currency: str
    total_value: Decimal
    groups: list[AggregateGroup]
    generated_at: str


class PortfolioSummary(BaseModel):
    base_currency: str
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    generated_at: str
    holdings_count: int
    missing_price_count: int
    missing_fx_count: int
