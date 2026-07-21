import uuid

from pydantic import BaseModel


class ImportPreviewRow(BaseModel):
    row_index: int
    owner_name: str
    owner_id: str | None
    institution_name: str
    institution_id: str | None
    account_name: str
    account_id: str | None
    instrument_name: str
    ticker: str | None
    instrument_id: str | None
    asset_type: str
    quantity: str | None
    currency: str | None
    cost_price: str | None
    current_price: str | None
    valuation_date: str | None
    exposure_group: str | None
    country: str | None
    liquidity_type: str | None
    errors: list[str]


class ImportBatchRead(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    row_count: int
    matched_count: int
    created_count: int
    error_count: int
    rows: list[ImportPreviewRow]
