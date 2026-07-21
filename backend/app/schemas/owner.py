import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import OwnerType


class OwnerBase(BaseModel):
    name: str
    owner_type: OwnerType = OwnerType.INDIVIDUAL
    display_order: int = 0


class OwnerCreate(OwnerBase):
    pass


class OwnerUpdate(BaseModel):
    name: str | None = None
    owner_type: OwnerType | None = None
    display_order: int | None = None


class OwnerRead(OwnerBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
