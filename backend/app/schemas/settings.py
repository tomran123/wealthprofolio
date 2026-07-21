from pydantic import BaseModel


class AppSettingsRead(BaseModel):
    base_currency: str


class AppSettingsUpdate(BaseModel):
    base_currency: str
