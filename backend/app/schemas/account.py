import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import AccountType


class AccountBase(BaseModel):
    institution_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    account_type: AccountType = AccountType.BROKERAGE
    base_currency: str = "USD"
    account_number_mask: str | None = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    institution_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    name: str | None = None
    account_type: AccountType | None = None
    base_currency: str | None = None
    account_number_mask: str | None = None


class AccountRead(AccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class AccountWithNames(AccountRead):
    institution_name: str
    owner_name: str
