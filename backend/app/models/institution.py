from sqlalchemy import Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import InstitutionType


class Institution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bank, broker, or other custodian holding accounts."""

    __tablename__ = "institutions"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution_type: Mapped[InstitutionType] = mapped_column(
        SAEnum(InstitutionType, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=InstitutionType.BANK,
        nullable=False,
    )
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="institution")
