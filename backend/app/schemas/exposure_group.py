import uuid

from pydantic import BaseModel, ConfigDict


class ExposureGroupBase(BaseModel):
    name: str
    description: str | None = None


class ExposureGroupCreate(ExposureGroupBase):
    pass


class ExposureGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ExposureGroupRead(ExposureGroupBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
