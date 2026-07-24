import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import TransactionSource, TransactionType


class TransactionCommon(BaseModel):
    account_id: uuid.UUID
    currency: str = Field(min_length=3, max_length=3)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    fee_currency: str | None = Field(default=None, min_length=3, max_length=3)
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    settlement_date: date | None = None
    external_ref: str | None = Field(default=None, max_length=100)
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL


class BuyTransactionCreate(TransactionCommon):
    instrument_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)


class SellTransactionCreate(BuyTransactionCreate):
    pass


class TransferCreate(BaseModel):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    settlement_date: date | None = None
    external_ref: str | None = Field(default=None, max_length=100)
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL

    @model_validator(mode="after")
    def accounts_must_differ(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("transfer_accounts_must_differ")
        return self


class FXExchangeCreate(BaseModel):
    account_id: uuid.UUID
    from_currency: str = Field(min_length=3, max_length=3)
    from_amount: Decimal = Field(gt=0)
    to_currency: str = Field(min_length=3, max_length=3)
    to_amount: Decimal = Field(gt=0)
    rate: Decimal | None = Field(default=None, gt=0)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    fee_currency: str | None = Field(default=None, min_length=3, max_length=3)
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL

    @model_validator(mode="after")
    def currencies_must_differ(self):
        if self.from_currency.upper() == self.to_currency.upper():
            raise ValueError("fx_currencies_must_differ")
        return self


class IncomeTransactionCreate(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    transaction_type: TransactionType
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL

    @model_validator(mode="after")
    def income_type_only(self):
        if self.transaction_type not in (TransactionType.DIVIDEND, TransactionType.INTEREST):
            raise ValueError("income_type_must_be_dividend_or_interest")
        return self


class FeeTransactionCreate(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    instrument_id: uuid.UUID | None = None
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL


class CashTransactionCreate(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    transaction_type: TransactionType
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL

    @model_validator(mode="after")
    def cash_type_only(self):
        if self.transaction_type not in (TransactionType.DEPOSIT, TransactionType.WITHDRAW):
            raise ValueError("cash_type_must_be_deposit_or_withdraw")
        return self


class ManualAdjustmentCreate(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    delta_quantity: Decimal
    currency: str = Field(min_length=3, max_length=3)
    trade_date: date = Field(default_factory=date.today)
    executed_at: datetime | None = None
    note: str | None = None
    source: TransactionSource = TransactionSource.MANUAL


class TransactionMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_date: date | None = None
    executed_at: datetime | None = None
    settlement_date: date | None = None
    external_ref: str | None = Field(default=None, max_length=100)
    note: str | None = None

    @model_validator(mode="after")
    def trade_date_must_not_be_null(self):
        if "trade_date" in self.model_fields_set and self.trade_date is None:
            raise ValueError("trade_date_must_not_be_null")
        return self


class TransactionRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    account_id: uuid.UUID
    account_name: str
    instrument_id: uuid.UUID | None
    instrument_name: str | None
    instrument_symbol: str | None
    transaction_type: TransactionType
    quantity: Decimal
    price: Decimal | None
    currency: str
    amount: Decimal
    fee: Decimal
    fee_currency: str
    trade_date: date
    executed_at: datetime | None
    settlement_date: date | None
    external_ref: str | None
    linked_transaction_id: uuid.UUID | None
    note: str | None
    source: TransactionSource
    is_reversed: bool
    reversed_by_id: uuid.UUID | None


class TransactionSummary(BaseModel):
    total_buy: Decimal
    total_sell: Decimal
    net_cash_flow: Decimal


class TransactionPage(BaseModel):
    items: list[TransactionRead]
    total: int
    offset: int
    limit: int
    summary: TransactionSummary


class TransactionMutationResult(BaseModel):
    transactions: list[TransactionRead]
