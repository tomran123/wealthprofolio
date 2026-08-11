import uuid

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    active_family_id: uuid.UUID
    role: str
