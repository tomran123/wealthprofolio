import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, FamilyScopedMixin


class AppSetting(FamilyScopedMixin, Base):
    """Generic key-value application settings store (base currency, etc.)."""

    __tablename__ = "app_settings"

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
