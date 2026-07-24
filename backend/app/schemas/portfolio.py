from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
    total_liabilities: Decimal
    liability_groups: list[AggregateGroup]
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


class RefreshResultRead(BaseModel):
    success_count: int
    kept_count: int
    failed_count: int
    failed_symbols: list[str]
    errors: list[dict[str, str]] = []
    fx_error: str | None = None
    refreshed_at: str
    snapshot_id: str


class ValuationSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: str
    base_currency: str
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    allocation_json: dict
    refresh_result_json: dict


class ValuationSnapshotPage(BaseModel):
    items: list[ValuationSnapshotRead]
    total: int
    offset: int
    limit: int
