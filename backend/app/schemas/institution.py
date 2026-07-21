import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import InstitutionType


class InstitutionBase(BaseModel):
    name: str
    institution_type: InstitutionType = InstitutionType.BANK
    country: str | None = None


class InstitutionCreate(InstitutionBase):
    pass


class InstitutionUpdate(BaseModel):
    name: str | None = None
    institution_type: InstitutionType | None = None
    country: str | None = None


class InstitutionRead(InstitutionBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
