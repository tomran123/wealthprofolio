import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import HoldingSource


class HoldingSetRequest(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal


class HoldingAdjustRequest(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    delta_quantity: Decimal


class HoldingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal
    source: HoldingSource


class HoldingWithInstrument(HoldingRead):
    instrument_name: str
    instrument_symbol: str | None
