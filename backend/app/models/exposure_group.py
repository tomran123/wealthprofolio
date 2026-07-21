from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExposureGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A manually-tagged underlying market exposure (e.g. 'S&P 500', 'Gold') that groups
    together instruments which track the same underlying exposure even if they are
    different securities (SPY / VOO / IVV)."""

    __tablename__ = "exposure_groups"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    instruments: Mapped[list["Instrument"]] = relationship("Instrument", back_populates="exposure_group")
