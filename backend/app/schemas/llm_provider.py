import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import LLMRole


class LLMProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    provider_key: str = Field(min_length=1, max_length=30)
    role: LLMRole
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=80)
    is_active: bool = False


class LLMProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    provider_key: str | None = Field(default=None, min_length=1, max_length=30)
    role: LLMRole | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=300)
    api_key: str | None = Field(default=None, min_length=1)
    model_name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None


class LLMProviderRead(BaseModel):
    id: uuid.UUID
    name: str
    provider_key: str
    role: LLMRole
    base_url: str
    model_name: str
    is_active: bool
    has_api_key: bool
    created_at: datetime
    updated_at: datetime
