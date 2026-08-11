from typing import TYPE_CHECKING

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FamilyScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.instrument import Instrument


class ExposureGroup(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    """A manually-tagged underlying market exposure (e.g. 'S&P 500', 'Gold') that groups
    together instruments which track the same underlying exposure even if they are
    different securities (SPY / VOO / IVV)."""

    __tablename__ = "exposure_groups"
    __table_args__ = (
        UniqueConstraint(
            "family_id",
            "name",
            name="uq_exposure_groups_family_name",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    instruments: Mapped[list["Instrument"]] = relationship("Instrument", back_populates="exposure_group")
